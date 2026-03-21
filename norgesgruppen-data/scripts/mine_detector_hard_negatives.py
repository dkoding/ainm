from __future__ import annotations

import argparse
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
import sys

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from evaluate_local import build_ground_truth
from ngd_utils import image_records_by_id, load_json, resolve_image_path, save_json
from score_submission_run import load_selected_image_ids, run_submission


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine detector false positives to use as junk negatives.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument("images_dir", type=Path, help="Directory containing the shelf images")
    parser.add_argument("submission_dir", type=Path, help="Submission directory containing run.py and weights")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/crops/junk_negatives"),
        help="Where to write the mined junk crops.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/crops/junk_negatives_manifest.json"),
        help="Where to write the mined junk manifest JSON.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/junk_negatives.json"),
        help="Where to write the mining report JSON.",
    )
    parser.add_argument("--split", type=Path, help="Optional split JSON.")
    parser.add_argument(
        "--split-name",
        choices=("train", "val"),
        default="train",
        help="Which split to mine from when --split is provided.",
    )
    parser.add_argument("--min-score", type=float, default=0.20, help="Minimum detector score to keep as a candidate.")
    parser.add_argument("--max-iou", type=float, default=0.10, help="Maximum IoU with any GT box to count as junk.")
    parser.add_argument("--max-negatives-per-image", type=int, default=10)
    parser.add_argument("--padding", type=float, default=0.05, help="Padding ratio applied to mined negative boxes.")
    parser.add_argument("--min-size", type=int, default=8, help="Skip mined crops smaller than this many pixels.")
    parser.add_argument(
        "--predictions-output",
        type=Path,
        default=Path("data/reports/junk_negative_predictions.json"),
        help="Where to cache the raw detector predictions JSON.",
    )
    parser.add_argument(
        "--python-executable",
        type=Path,
        help="Optional Python interpreter to use for submission/run.py instead of the current one.",
    )
    parser.add_argument(
        "--pythonpath",
        action="append",
        type=Path,
        default=[],
        help="Optional extra PYTHONPATH entry for local scoring. Repeatable.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from PIL import Image

    annotations_path = args.annotations.resolve()
    images_dir = args.images_dir.resolve()
    submission_dir = args.submission_dir.resolve()
    output_root = args.output_root.resolve()
    manifest_path = args.manifest.resolve()
    report_path = args.report.resolve()
    predictions_output = args.predictions_output.resolve()

    output_root.mkdir(parents=True, exist_ok=True)
    junk_dir = output_root / "junk"
    if junk_dir.exists():
        for existing in junk_dir.iterdir():
            if existing.is_file() and existing.suffix.lower() in IMAGE_SUFFIXES:
                existing.unlink()
    junk_dir.mkdir(parents=True, exist_ok=True)

    coco = load_json(annotations_path)
    selected_image_ids = load_selected_image_ids(
        coco,
        args.split.resolve() if args.split else None,
        args.split_name,
    )
    images_by_id = image_records_by_id(coco)
    gt_by_image = build_ground_truth(coco, selected_image_ids)

    original_config_path = submission_dir / "submission_config.json"
    original_config_text = original_config_path.read_text(encoding="utf-8") if original_config_path.exists() else None
    detector_only_config = build_detector_only_config(original_config_text)
    try:
        original_config_path.write_text(detector_only_config, encoding="utf-8")
        run_submission(
            submission_dir=submission_dir,
            image_dir=images_dir,
            predictions_output=predictions_output,
            python_executable=args.python_executable.resolve() if args.python_executable else None,
            pythonpath_entries=[path.resolve() for path in args.pythonpath],
        )
    finally:
        restore_config(original_config_path, original_config_text)

    predictions = load_json(predictions_output)
    manifest = []
    image_count_with_negatives = 0
    candidate_count = 0
    for image_id in sorted(selected_image_ids):
        image_record = images_by_id[image_id]
        image_path = resolve_image_path(images_dir, str(image_record["file_name"]))
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        image_predictions = [
            prediction
            for prediction in predictions
            if int(prediction["image_id"]) == image_id and float(prediction["score"]) >= args.min_score
        ]
        image_predictions.sort(key=lambda prediction: float(prediction["score"]), reverse=True)

        kept_for_image = 0
        for prediction in image_predictions:
            candidate_count += 1
            pred_box = prediction.get("bbox", [0, 0, 0, 0])
            if len(pred_box) != 4 or pred_box[2] <= 0 or pred_box[3] <= 0:
                continue
            best_iou = max((iou_xywh(pred_box, gt["bbox"]) for gt in gt_by_image.get(image_id, [])), default=0.0)
            if best_iou > args.max_iou:
                continue
            crop_box = padded_box_xywh(pred_box, width, height, args.padding)
            crop_width = crop_box[2] - crop_box[0]
            crop_height = crop_box[3] - crop_box[1]
            if crop_width < args.min_size or crop_height < args.min_size:
                continue
            destination = junk_dir / (
                f"img_{image_id:05d}_junk_{kept_for_image + 1:03d}_"
                f"score_{int(round(float(prediction['score']) * 1000)):04d}.jpg"
            )
            image.crop(crop_box).save(destination, format="JPEG")
            manifest.append(
                {
                    "annotation_id": -(len(manifest) + 1),
                    "category_id": -2,
                    "image_id": image_id,
                    "source_file": str(image_record["file_name"]),
                    "crop_file": destination.as_posix(),
                    "prediction_bbox": pred_box,
                    "crop_box": list(crop_box),
                    "score": round(float(prediction["score"]), 6),
                    "max_iou_to_gt": round(float(best_iou), 6),
                }
            )
            kept_for_image += 1
            if kept_for_image >= args.max_negatives_per_image:
                break
        if kept_for_image > 0:
            image_count_with_negatives += 1

    save_json(manifest_path, manifest)
    save_json(
        report_path,
        {
            "annotations_path": str(annotations_path),
            "images_dir": str(images_dir),
            "submission_dir": str(submission_dir),
            "predictions_output": str(predictions_output),
            "output_root": str(output_root),
            "manifest": str(manifest_path),
            "settings": {
                "split": str(args.split.resolve()) if args.split else None,
                "split_name": args.split_name,
                "min_score": args.min_score,
                "max_iou": args.max_iou,
                "max_negatives_per_image": args.max_negatives_per_image,
                "padding": args.padding,
                "min_size": args.min_size,
            },
            "summary": {
                "selected_image_count": len(selected_image_ids),
                "prediction_candidate_count": candidate_count,
                "negative_crop_count": len(manifest),
                "images_with_negatives": image_count_with_negatives,
            },
        },
    )

    print(f"manifest={manifest_path}")
    print(f"report={report_path}")
    print(f"negative_crops={len(manifest)}")


def build_detector_only_config(original_config_text: str | None) -> str:
    import json

    config = json.loads(original_config_text) if original_config_text else {}
    config["detection_only"] = True
    classifier = dict(config.get("classifier", {}))
    classifier["enabled"] = False
    config["classifier"] = classifier
    return json.dumps(config, indent=2) + "\n"


def restore_config(path: Path, original_config_text: str | None) -> None:
    if original_config_text is None:
        if path.exists():
            path.unlink()
        return
    path.write_text(original_config_text, encoding="utf-8")


def iou_xywh(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, aw, ah = [float(value) for value in box_a]
    bx1, by1, bw, bh = [float(value) for value in box_b]
    ax2 = ax1 + aw
    ay2 = ay1 + ah
    bx2 = bx1 + bw
    by2 = by1 + bh
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0
    union = (aw * ah) + (bw * bh) - inter_area
    if union <= 0.0:
        return 0.0
    return inter_area / union


def padded_box_xywh(bbox: list[float], image_width: int, image_height: int, padding: float) -> tuple[int, int, int, int]:
    x, y, width, height = [float(value) for value in bbox]
    pad_w = width * padding
    pad_h = height * padding
    x1 = max(0, int(round(x - pad_w)))
    y1 = max(0, int(round(y - pad_h)))
    x2 = min(image_width, int(round(x + width + pad_w)))
    y2 = min(image_height, int(round(y + height + pad_h)))
    return (x1, y1, x2, y2)


if __name__ == "__main__":
    main()
