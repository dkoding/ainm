import argparse
import json
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
TORCH_LOAD_PATCHED = False
DEFAULT_CONFIG = {
    "backend": "auto",
    "allow_empty_predictions": False,
    "detection_only": False,
    "confidence_threshold": 0.2,
    "image_size": 1280,
    "max_detections": 300,
    "class_map_path": "class_map.json",
    "ultralytics": {
        "weight_candidates": ["best.pt", "model.pt", "weights/best.pt"],
        "half": False,
    },
    "classifier": {
        "enabled": False,
        "weight_candidates": ["best_crop_classifier.pt", "crop_classifier.pt", "weights/best_crop_classifier.pt"],
        "input_size": 224,
        "batch_size": 64,
        "min_crop_size": 8,
        "score_mode": "blend_mul",
        "score_alpha": 0.5,
    },
    "onnx": {
        "weight_candidates": ["model.onnx", "weights/model.onnx"],
        "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "input_size": [1280, 1280],
        "box_format": "cxcywh",
        "score_mode": "class",
        "nms_iou_threshold": 0.5,
        "class_agnostic_nms": False,
        "output_index": 0,
        "input_name": None,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    config = load_config(root / "submission_config.json")
    predictor = build_predictor(root, config)

    predictions = []
    for image_path in sorted(Path(args.input).iterdir()):
        if image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        predictions.extend(predictor.predict(image_path))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(predictions), encoding="utf-8")


def load_config(path: Path) -> dict:
    merged = clone_config(DEFAULT_CONFIG)
    if not path.exists():
        return merged
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return deep_merge(merged, loaded)


def clone_config(config: dict) -> dict:
    return json.loads(json.dumps(config))


def deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
            continue
        base[key] = value
    return base


def build_predictor(root: Path, config: dict):
    classifier_enabled = bool(config.get("classifier", {}).get("enabled", False))
    classifier = None
    classifier_failure = None
    if classifier_enabled:
        try:
            classifier = load_crop_classifier(root, config)
        except Exception as exc:
            classifier_failure = f"classifier failed: {exc}"

    detector_config = clone_config(config)
    if classifier_enabled:
        detector_config["detection_only"] = True

    class_mapper = load_class_mapper(root, detector_config)
    backend = str(config.get("backend", "auto")).lower()
    allow_empty = bool(config.get("allow_empty_predictions", False))
    failures = []
    if classifier_failure:
        failures.append(classifier_failure)

    if backend in {"auto", "onnx"}:
        weights_path = first_existing_path(root, detector_config.get("onnx", {}).get("weight_candidates", []))
        if weights_path is not None:
            try:
                predictor = OnnxPredictor(weights_path, detector_config, class_mapper)
                if classifier_enabled:
                    if classifier is None:
                        raise RuntimeError(classifier_failure or "classifier enabled but unavailable")
                    return CropClassifierRefiner(predictor, classifier)
                return predictor
            except Exception as exc:
                failures.append(f"onnx backend failed for {weights_path.name}: {exc}")
        elif backend == "onnx":
            failures.append("onnx backend selected but no matching weight file was found")

    if backend in {"auto", "ultralytics"}:
        weights_path = first_existing_path(root, detector_config.get("ultralytics", {}).get("weight_candidates", []))
        if weights_path is not None:
            try:
                predictor = UltralyticsPredictor(weights_path, detector_config, class_mapper)
                if classifier_enabled:
                    if classifier is None:
                        raise RuntimeError(classifier_failure or "classifier enabled but unavailable")
                    return CropClassifierRefiner(predictor, classifier)
                return predictor
            except Exception as exc:
                failures.append(f"ultralytics backend failed for {weights_path.name}: {exc}")
        elif backend == "ultralytics":
            failures.append("ultralytics backend selected but no matching weight file was found")

    if allow_empty:
        if failures:
            for failure in failures:
                print(f"warning: {failure}")
        return EmptyPredictor()

    details = "; ".join(failures) if failures else "no supported model weights found"
    raise RuntimeError(f"Unable to initialize submission backend: {details}")


def load_class_mapper(root: Path, config: dict):
    class_map_path = config.get("class_map_path")
    if not class_map_path:
        return IdentityClassMapper()

    path = root / str(class_map_path)
    if not path.exists():
        return IdentityClassMapper()

    loaded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        mapping = {index: int(category_id) for index, category_id in enumerate(loaded)}
        return ExplicitClassMapper(mapping)
    if isinstance(loaded, dict):
        mapping = {int(index): int(category_id) for index, category_id in loaded.items()}
        return ExplicitClassMapper(mapping)
    raise ValueError(f"Unsupported class map format in {path}")


def first_existing_path(root: Path, candidates: list) -> Path | None:
    for candidate in candidates:
        path = root / str(candidate)
        if path.exists():
            return path
    return None


def extract_image_id(image_path: Path) -> int:
    stem = image_path.stem
    parts = stem.split("_")
    try:
        return int(parts[-1])
    except ValueError as exc:
        raise ValueError(f"Unable to parse image_id from {image_path.name}") from exc


def make_prediction(image_id: int, category_id: int, box_xyxy: list[float], score: float) -> dict:
    x1, y1, x2, y2 = box_xyxy
    return {
        "image_id": image_id,
        "category_id": int(category_id),
        "bbox": [
            round(float(x1), 1),
            round(float(y1), 1),
            round(float(max(0.0, x2 - x1)), 1),
            round(float(max(0.0, y2 - y1)), 1),
        ],
        "score": round(float(score), 3),
    }


def clamp_box(box_xyxy: list[float], width: float, height: float) -> list[float]:
    x1, y1, x2, y2 = box_xyxy
    x1 = min(max(x1, 0.0), width)
    x2 = min(max(x2, 0.0), width)
    y1 = min(max(y1, 0.0), height)
    y2 = min(max(y2, 0.0), height)
    return [x1, y1, x2, y2]


class IdentityClassMapper:
    def map(self, class_index: int) -> int:
        return int(class_index)


class ExplicitClassMapper:
    def __init__(self, mapping: dict[int, int]):
        self.mapping = dict(mapping)

    def map(self, class_index: int) -> int:
        if class_index not in self.mapping:
            raise KeyError(f"Missing class map entry for model class {class_index}")
        return int(self.mapping[class_index])


class EmptyPredictor:
    def predict(self, image_path: Path) -> list[dict]:
        return []


def load_crop_classifier(root: Path, config: dict):
    classifier_config = config.get("classifier", {})
    if not bool(classifier_config.get("enabled", False)):
        return None
    weights_path = first_existing_path(root, classifier_config.get("weight_candidates", []))
    if weights_path is None:
        raise RuntimeError("classifier is enabled but no matching checkpoint was found")
    return CropClassifier(weights_path, classifier_config)


class CropClassifierRefiner:
    def __init__(self, detector, classifier):
        self.detector = detector
        self.classifier = classifier

    def predict(self, image_path: Path) -> list[dict]:
        from PIL import Image

        predictions = self.detector.predict(image_path)
        if not predictions:
            return predictions
        image = Image.open(image_path).convert("RGB")
        return self.classifier.refine_predictions(image, predictions)


class CropClassifier:
    def __init__(self, weights_path: Path, config: dict):
        import torch
        from torchvision import transforms

        payload = torch.load(weights_path, map_location="cpu")
        self.arch = str(payload["arch"])
        self.category_ids = [int(class_name) for class_name in payload["class_names"]]
        self.batch_size = max(1, int(config.get("batch_size", 64)))
        self.min_crop_size = max(1, int(config.get("min_crop_size", 8)))
        self.score_mode = str(config.get("score_mode", "blend_mul")).lower()
        self.score_alpha = float(config.get("score_alpha", 0.5))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = build_crop_classifier_model(self.arch, len(self.category_ids))
        self.model.load_state_dict(payload["model_state_dict"])
        self.model.to(self.device)
        self.model.eval()

        input_size = int(config.get("input_size", 224))
        normalize = transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225))
        self.transform = transforms.Compose(
            [
                transforms.Resize(int(round(input_size * 1.15))),
                transforms.CenterCrop(input_size),
                transforms.ToTensor(),
                normalize,
            ]
        )

    def refine_predictions(self, image, predictions: list[dict]) -> list[dict]:
        import torch

        image_width, image_height = image.size
        valid_indices = []
        crop_tensors = []
        refined_predictions = [dict(prediction) for prediction in predictions]

        for index, prediction in enumerate(predictions):
            box_xyxy = clamp_box(prediction_xywh_to_xyxy(prediction["bbox"]), image_width, image_height)
            crop_box = normalize_crop_box(box_xyxy)
            if crop_box is None:
                continue
            crop_width = crop_box[2] - crop_box[0]
            crop_height = crop_box[3] - crop_box[1]
            if crop_width < self.min_crop_size or crop_height < self.min_crop_size:
                continue
            crop_image = image.crop(crop_box)
            crop_tensors.append(self.transform(crop_image))
            valid_indices.append(index)

        if not crop_tensors:
            return refined_predictions

        with torch.no_grad():
            for offset in range(0, len(crop_tensors), self.batch_size):
                batch_indices = valid_indices[offset : offset + self.batch_size]
                batch_tensors = torch.stack(crop_tensors[offset : offset + self.batch_size]).to(self.device)
                with torch.amp.autocast(device_type=self.device, enabled=self.device == "cuda"):
                    logits = self.model(batch_tensors)
                probabilities = torch.softmax(logits, dim=1)
                top_scores, top_indices = probabilities.max(dim=1)
                for row, prediction_index in enumerate(batch_indices):
                    category_id = self.category_ids[int(top_indices[row].item())]
                    classifier_score = float(top_scores[row].item())
                    detection_score = float(refined_predictions[prediction_index]["score"])
                    refined_predictions[prediction_index]["category_id"] = category_id
                    refined_predictions[prediction_index]["score"] = round(
                        combine_scores(
                            detection_score=detection_score,
                            classifier_score=classifier_score,
                            score_mode=self.score_mode,
                            score_alpha=self.score_alpha,
                        ),
                        3,
                    )
        return refined_predictions


def build_crop_classifier_model(arch: str, num_classes: int):
    import torch
    from torchvision.models import convnext_small, convnext_tiny, resnet18, resnet50

    if arch == "resnet18":
        model = resnet18(weights=None)
        model.fc = torch.nn.Linear(model.fc.in_features, num_classes)
        return model
    if arch == "resnet50":
        model = resnet50(weights=None)
        model.fc = torch.nn.Linear(model.fc.in_features, num_classes)
        return model
    if arch == "convnext_tiny":
        model = convnext_tiny(weights=None)
        model.classifier[2] = torch.nn.Linear(model.classifier[2].in_features, num_classes)
        return model
    if arch == "convnext_small":
        model = convnext_small(weights=None)
        model.classifier[2] = torch.nn.Linear(model.classifier[2].in_features, num_classes)
        return model
    raise ValueError(f"Unsupported crop-classifier architecture: {arch}")


def prediction_xywh_to_xyxy(bbox: list[float]) -> list[float]:
    x, y, width, height = bbox
    return [float(x), float(y), float(x + width), float(y + height)]


def normalize_crop_box(box_xyxy: list[float]) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = [int(round(value)) for value in box_xyxy]
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def combine_scores(detection_score: float, classifier_score: float, score_mode: str, score_alpha: float) -> float:
    if score_mode == "detector":
        score = detection_score
    elif score_mode == "classifier":
        score = classifier_score
    elif score_mode == "geometric_mean":
        score = max(0.0, detection_score * classifier_score) ** 0.5
    elif score_mode == "blend":
        score = (score_alpha * detection_score) + ((1.0 - score_alpha) * classifier_score)
    elif score_mode == "blend_mul":
        score = detection_score * (score_alpha + ((1.0 - score_alpha) * classifier_score))
    else:
        score = detection_score * classifier_score
    return min(1.0, max(0.0, float(score)))


class UltralyticsPredictor:
    def __init__(self, weights_path: Path, config: dict, class_mapper):
        import torch
        from ultralytics import YOLO

        patch_torch_load_for_ultralytics(torch)
        backend_config = config.get("ultralytics", {})
        self.class_mapper = class_mapper
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = YOLO(str(weights_path))
        self.detection_only = bool(config.get("detection_only", False))
        self.confidence_threshold = float(config.get("confidence_threshold", 0.25))
        self.image_size = int(config.get("image_size", 1280))
        self.max_detections = int(config.get("max_detections", 300))
        self.half = bool(backend_config.get("half", False))

    def predict(self, image_path: Path) -> list[dict]:
        image_id = extract_image_id(image_path)
        results = self.model(
            str(image_path),
            device=self.device,
            conf=self.confidence_threshold,
            imgsz=self.image_size,
            verbose=False,
            max_det=self.max_detections,
            half=self.half,
        )
        predictions = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for index in range(len(boxes)):
                x1, y1, x2, y2 = boxes.xyxy[index].tolist()
                class_index = int(boxes.cls[index].item())
                category_id = 0 if self.detection_only else self.class_mapper.map(class_index)
                predictions.append(
                    make_prediction(
                        image_id=image_id,
                        category_id=category_id,
                        box_xyxy=[x1, y1, x2, y2],
                        score=float(boxes.conf[index].item()),
                    )
                )
        return predictions


def patch_torch_load_for_ultralytics(torch_module) -> None:
    global TORCH_LOAD_PATCHED
    if TORCH_LOAD_PATCHED:
        return
    original_load = torch_module.load

    def patched_load(*args, **kwargs):
        # ultralytics 8.1.0 checkpoints expect the pre-2.6 torch.load behavior.
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    torch_module.load = patched_load
    TORCH_LOAD_PATCHED = True


class OnnxPredictor:
    def __init__(self, weights_path: Path, config: dict, class_mapper):
        import numpy as np
        import onnxruntime as ort

        backend_config = config.get("onnx", {})
        providers = list(backend_config.get("providers", ["CUDAExecutionProvider", "CPUExecutionProvider"]))
        self.session = ort.InferenceSession(str(weights_path), providers=providers)
        input_meta = self.session.get_inputs()[0]
        self.input_name = backend_config.get("input_name") or input_meta.name
        self.input_dtype = np.float16 if input_meta.type == "tensor(float16)" else np.float32
        self.output_index = int(backend_config.get("output_index", 0))
        self.box_format = str(backend_config.get("box_format", "cxcywh")).lower()
        self.score_mode = str(backend_config.get("score_mode", "class")).lower()
        input_size = backend_config.get("input_size", [config.get("image_size", 1280), config.get("image_size", 1280)])
        self.input_width, self.input_height = normalize_input_size(input_size)
        self.class_agnostic_nms = bool(backend_config.get("class_agnostic_nms", False))
        self.nms_iou_threshold = float(backend_config.get("nms_iou_threshold", 0.5))
        self.class_mapper = class_mapper
        self.detection_only = bool(config.get("detection_only", False))
        self.confidence_threshold = float(config.get("confidence_threshold", 0.25))
        self.max_detections = int(config.get("max_detections", 300))

    def predict(self, image_path: Path) -> list[dict]:
        import numpy as np
        from PIL import Image

        image_id = extract_image_id(image_path)
        image = Image.open(image_path).convert("RGB")
        image_width, image_height = image.size
        tensor, scale, pad_left, pad_top = preprocess_image(
            image,
            self.input_width,
            self.input_height,
            dtype=self.input_dtype,
        )
        outputs = self.session.run(None, {self.input_name: tensor})
        raw_output = outputs[self.output_index]
        decoded = decode_onnx_rows(raw_output)
        rows = self.filter_rows(decoded)
        boxes = self.apply_nms(rows)

        predictions = []
        for row in boxes:
            box_xyxy = rescale_box(
                box_xyxy=row["box_xyxy"],
                scale=scale,
                pad_left=pad_left,
                pad_top=pad_top,
                image_width=image_width,
                image_height=image_height,
            )
            box_xyxy = clamp_box(box_xyxy, image_width, image_height)
            if box_xyxy[2] <= box_xyxy[0] or box_xyxy[3] <= box_xyxy[1]:
                continue
            category_id = 0 if self.detection_only else self.class_mapper.map(row["class_index"])
            predictions.append(
                make_prediction(
                    image_id=image_id,
                    category_id=category_id,
                    box_xyxy=box_xyxy,
                    score=row["score"],
                )
            )
        return predictions

    def filter_rows(self, rows) -> list[dict]:
        filtered = []
        for row in rows:
            decoded = decode_prediction_row(row, self.box_format, self.score_mode)
            if decoded is None:
                continue
            if decoded["score"] < self.confidence_threshold:
                continue
            filtered.append(decoded)
        filtered.sort(key=lambda item: item["score"], reverse=True)
        return filtered[: self.max_detections * 5]

    def apply_nms(self, rows: list[dict]) -> list[dict]:
        selected = []
        for row in rows:
            suppressed = False
            for chosen in selected:
                if not self.class_agnostic_nms and chosen["class_index"] != row["class_index"]:
                    continue
                if iou_xyxy(chosen["box_xyxy"], row["box_xyxy"]) >= self.nms_iou_threshold:
                    suppressed = True
                    break
            if not suppressed:
                selected.append(row)
            if len(selected) >= self.max_detections:
                break
        return selected


def normalize_input_size(value) -> tuple[int, int]:
    if isinstance(value, int):
        return int(value), int(value)
    if isinstance(value, list) and len(value) == 2:
        return int(value[0]), int(value[1])
    raise ValueError(f"Unsupported input_size value: {value}")


def preprocess_image(image, input_width: int, input_height: int, dtype):
    import numpy as np
    from PIL import Image

    original_width, original_height = image.size
    scale = min(input_width / original_width, input_height / original_height)
    resized_width = max(1, int(round(original_width * scale)))
    resized_height = max(1, int(round(original_height * scale)))
    resized = image.resize((resized_width, resized_height), Image.Resampling.BILINEAR)

    pad_left = (input_width - resized_width) // 2
    pad_top = (input_height - resized_height) // 2
    canvas = Image.new("RGB", (input_width, input_height), (114, 114, 114))
    canvas.paste(resized, (pad_left, pad_top))

    array = np.asarray(canvas, dtype=np.float32) / 255.0
    array = array.transpose(2, 0, 1)[None, ...]
    return array.astype(dtype, copy=False), scale, pad_left, pad_top


def decode_onnx_rows(raw_output):
    import numpy as np

    output = np.asarray(raw_output)
    if output.ndim == 4:
        output = output.reshape(output.shape[0], output.shape[1], -1)
    if output.ndim == 3:
        output = output[0]
        if output.shape[0] <= 128 and output.shape[1] > output.shape[0]:
            output = output.transpose(1, 0)
    if output.ndim != 2:
        raise ValueError(f"Unsupported ONNX output shape: {tuple(output.shape)}")
    return output


def decode_prediction_row(row, box_format: str, score_mode: str):
    import numpy as np

    values = np.asarray(row).astype(float).tolist()
    if len(values) < 5:
        return None

    if len(values) == 5:
        box_xyxy = normalize_box(values[:4], box_format)
        score = float(values[4])
        return {"box_xyxy": box_xyxy, "score": score, "class_index": 0}

    if len(values) == 6:
        box_xyxy = normalize_box(values[:4], box_format)
        score = float(values[4])
        class_index = int(round(values[5]))
        return {"box_xyxy": box_xyxy, "score": score, "class_index": class_index}

    if score_mode == "objectness_class":
        objectness = float(values[4])
        class_scores = [objectness * float(score) for score in values[5:]]
    else:
        class_scores = [float(score) for score in values[4:]]

    if not class_scores:
        return None

    best_score = max(class_scores)
    class_index = class_scores.index(best_score)
    box_xyxy = normalize_box(values[:4], box_format)
    return {"box_xyxy": box_xyxy, "score": best_score, "class_index": class_index}


def normalize_box(values: list[float], box_format: str) -> list[float]:
    if box_format == "xyxy":
        return [float(values[0]), float(values[1]), float(values[2]), float(values[3])]
    if box_format == "cxcywh":
        center_x, center_y, width, height = [float(value) for value in values]
        return [
            center_x - width / 2.0,
            center_y - height / 2.0,
            center_x + width / 2.0,
            center_y + height / 2.0,
        ]
    raise ValueError(f"Unsupported box_format: {box_format}")


def rescale_box(
    box_xyxy: list[float],
    scale: float,
    pad_left: float,
    pad_top: float,
    image_width: float,
    image_height: float,
) -> list[float]:
    x1, y1, x2, y2 = box_xyxy
    x1 = (x1 - pad_left) / scale
    x2 = (x2 - pad_left) / scale
    y1 = (y1 - pad_top) / scale
    y2 = (y2 - pad_top) / scale
    return clamp_box([x1, y1, x2, y2], image_width, image_height)


def iou_xyxy(box_a: list[float], box_b: list[float]) -> float:
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    intersection = inter_w * inter_h
    if intersection <= 0.0:
        return 0.0
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


if __name__ == "__main__":
    main()
