import argparse
import json
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
DEFAULT_CONFIG = {
    "detection_only": True,
    "confidence_threshold": 0.2,
    "image_size": 1280,
    "weight_candidates": ["best.pt", "model.pt", "weights/best.pt"],
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
    output_path.write_text(json.dumps(predictions))


def load_config(path: Path) -> dict:
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    loaded = json.loads(path.read_text())
    merged = dict(DEFAULT_CONFIG)
    merged.update(loaded)
    return merged


def build_predictor(root: Path, config: dict):
    for candidate in config["weight_candidates"]:
        path = root / candidate
        if path.exists():
            try:
                return UltralyticsPredictor(path, config)
            except Exception as exc:
                print(f"warning: failed to load {path}: {exc}")
    return EmptyPredictor()


class EmptyPredictor:
    def predict(self, image_path: Path) -> list[dict]:
        return []


class UltralyticsPredictor:
    def __init__(self, weights_path: Path, config: dict):
        import torch
        from ultralytics import YOLO

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = YOLO(str(weights_path))
        self.detection_only = bool(config["detection_only"])
        self.confidence_threshold = float(config["confidence_threshold"])
        self.image_size = int(config["image_size"])

    def predict(self, image_path: Path) -> list[dict]:
        image_id = int(image_path.stem.split("_")[-1])
        results = self.model(
            str(image_path),
            device=self.device,
            conf=self.confidence_threshold,
            imgsz=self.image_size,
            verbose=False,
        )
        predictions = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for index in range(len(boxes)):
                x1, y1, x2, y2 = boxes.xyxy[index].tolist()
                category_id = 0 if self.detection_only else int(boxes.cls[index].item())
                predictions.append(
                    {
                        "image_id": image_id,
                        "category_id": category_id,
                        "bbox": [
                            round(float(x1), 1),
                            round(float(y1), 1),
                            round(float(x2 - x1), 1),
                            round(float(y2 - y1), 1),
                        ],
                        "score": round(float(boxes.conf[index].item()), 3),
                    }
                )
        return predictions


if __name__ == "__main__":
    main()
