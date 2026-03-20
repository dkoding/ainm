import argparse
import json
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
DEFAULT_CONFIG = {
    "backend": "auto",
    "allow_empty_predictions": True,
    "detection_only": True,
    "confidence_threshold": 0.2,
    "image_size": 1280,
    "max_detections": 300,
    "class_map_path": "class_map.json",
    "ultralytics": {
        "weight_candidates": ["best.pt", "model.pt", "weights/best.pt"],
        "half": False,
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
    class_mapper = load_class_mapper(root, config)
    backend = str(config.get("backend", "auto")).lower()
    allow_empty = bool(config.get("allow_empty_predictions", False))
    failures = []

    if backend in {"auto", "ultralytics"}:
        weights_path = first_existing_path(root, config.get("ultralytics", {}).get("weight_candidates", []))
        if weights_path is not None:
            try:
                return UltralyticsPredictor(weights_path, config, class_mapper)
            except Exception as exc:
                failures.append(f"ultralytics backend failed for {weights_path.name}: {exc}")
        elif backend == "ultralytics":
            failures.append("ultralytics backend selected but no matching weight file was found")

    if backend in {"auto", "onnx"}:
        weights_path = first_existing_path(root, config.get("onnx", {}).get("weight_candidates", []))
        if weights_path is not None:
            try:
                return OnnxPredictor(weights_path, config, class_mapper)
            except Exception as exc:
                failures.append(f"onnx backend failed for {weights_path.name}: {exc}")
        elif backend == "onnx":
            failures.append("onnx backend selected but no matching weight file was found")

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
    original_load = torch_module.load
    if getattr(original_load, "_ngd_force_weights_only_false", False):
        return

    def patched_load(*args, **kwargs):
        # ultralytics 8.1.0 checkpoints expect the pre-2.6 torch.load behavior.
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    patched_load._ngd_force_weights_only_false = True
    torch_module.load = patched_load


class OnnxPredictor:
    def __init__(self, weights_path: Path, config: dict, class_mapper):
        import onnxruntime as ort

        backend_config = config.get("onnx", {})
        providers = list(backend_config.get("providers", ["CUDAExecutionProvider", "CPUExecutionProvider"]))
        self.session = ort.InferenceSession(str(weights_path), providers=providers)
        self.input_name = backend_config.get("input_name") or self.session.get_inputs()[0].name
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
        tensor, scale, pad_left, pad_top = preprocess_image(image, self.input_width, self.input_height)
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


def preprocess_image(image, input_width: int, input_height: int):
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
    return array, scale, pad_left, pad_top


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
    if len(values) < 6:
        return None

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
