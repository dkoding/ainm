from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from evaluate_local import build_ground_truth, evaluate_classification, evaluate_detection, load_selected_image_ids
from ngd_utils import category_id_list, load_json, save_json

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage a trained checkpoint, run the real submission path, and record local score metrics."
    )
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument("image_dir", type=Path, help="Directory of images to score through submission/run.py")
    parser.add_argument(
        "--submission-dir",
        type=Path,
        default=Path("submission"),
        help="Directory containing the submission scaffold.",
    )
    parser.add_argument(
        "--weights",
        type=Path,
        help="Optional weight file to copy into the submission directory before scoring.",
    )
    parser.add_argument(
        "--staged-weight-name",
        default="best.pt",
        help="Filename to use inside the submission directory when staging --weights.",
    )
    parser.add_argument("--split", type=Path, help="Optional split JSON created by make_splits.py")
    parser.add_argument(
        "--split-name",
        choices=("train", "val"),
        default="val",
        help="Which split to evaluate when --split is provided.",
    )
    parser.add_argument(
        "--predictions-output",
        type=Path,
        required=True,
        help="Where to write the submission predictions JSON.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON output path for the combined summary.")
    parser.add_argument("--run-name", help="Optional label for the scored run.")
    parser.add_argument(
        "--output-zip",
        type=Path,
        help="Optional zip path for preflight packaging. Defaults to dist/<run_name>.zip.",
    )
    parser.add_argument("--skip-preflight", action="store_true", help="Skip submission preflight and zip creation.")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="Fail if submission/run.py writes zero predictions.",
    )
    parser.add_argument("--iou-threshold", type=float, default=0.5, help="IoU threshold for local scoring.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    annotations_path = args.annotations.resolve()
    image_dir = args.image_dir.resolve()
    submission_dir = args.submission_dir.resolve()
    run_name = resolve_run_name(args)
    output_zip = resolve_output_zip(args, run_name)

    if not (submission_dir / "run.py").exists():
        raise SystemExit(f"Missing run.py in submission directory: {submission_dir}")

    staged_weight_path = stage_weights(
        weights_path=args.weights.resolve() if args.weights else None,
        submission_dir=submission_dir,
        staged_weight_name=args.staged_weight_name,
    )
    predictions_output = args.predictions_output.resolve()
    predictions_output.parent.mkdir(parents=True, exist_ok=True)

    image_count = count_input_images(image_dir)
    if image_count <= 0:
        raise SystemExit(f"No supported images found under {image_dir}")

    inference_seconds = run_submission(submission_dir, image_dir, predictions_output)
    predictions = load_json(predictions_output)
    if not isinstance(predictions, list):
        raise SystemExit(f"Predictions output must be a JSON array: {predictions_output}")
    if args.fail_on_empty and not predictions:
        raise SystemExit("submission/run.py completed but wrote zero predictions.")

    summary = evaluate_predictions(
        annotations_path=annotations_path,
        split_path=args.split.resolve() if args.split else None,
        split_name=args.split_name,
        predictions=predictions,
        iou_threshold=args.iou_threshold,
    )
    summary.update(
        {
            "run_name": run_name,
            "input_image_count": image_count,
            "predictions_output": str(predictions_output),
            "inference_seconds": round(inference_seconds, 6),
            "average_inference_seconds": round(inference_seconds / image_count, 6),
            "submission_dir": str(submission_dir),
            "staged_weight_path": str(staged_weight_path) if staged_weight_path else None,
            "staged_weight_size_bytes": staged_weight_path.stat().st_size if staged_weight_path else None,
        }
    )

    if not args.skip_preflight:
        preflight_submission(
            submission_dir=submission_dir,
            image_dir=image_dir,
            output_zip=output_zip,
            fail_on_empty=args.fail_on_empty,
        )
        summary["output_zip"] = str(output_zip)
        summary["output_zip_size_bytes"] = output_zip.stat().st_size

    print_result(summary)
    if args.output:
        save_json(args.output.resolve(), summary)


def resolve_run_name(args: argparse.Namespace) -> str:
    if args.run_name:
        return args.run_name
    if args.weights:
        resolved = args.weights.resolve()
        if resolved.stem == "best" and resolved.parent.name == "weights":
            return resolved.parent.parent.name
        return resolved.stem
    return args.predictions_output.resolve().stem


def resolve_output_zip(args: argparse.Namespace, run_name: str) -> Path:
    if args.output_zip:
        return args.output_zip.resolve()
    return Path("dist") / f"{sanitize_file_name(run_name)}.zip"


def sanitize_file_name(value: str) -> str:
    cleaned = []
    for character in value:
        if character.isalnum() or character in {"-", "_", "."}:
            cleaned.append(character)
        else:
            cleaned.append("_")
    return "".join(cleaned) or "submission"


def stage_weights(weights_path: Path | None, submission_dir: Path, staged_weight_name: str) -> Path | None:
    if not weights_path:
        staged = submission_dir / staged_weight_name
        return staged if staged.exists() else None

    if not weights_path.exists():
        raise SystemExit(f"Missing weights file: {weights_path}")

    destination = submission_dir / staged_weight_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if weights_path.resolve() != destination.resolve():
        shutil.copy2(weights_path, destination)
    return destination


def count_input_images(image_dir: Path) -> int:
    return sum(1 for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def run_submission(submission_dir: Path, image_dir: Path, predictions_output: Path) -> float:
    command = [
        sys.executable,
        str(submission_dir / "run.py"),
        "--input",
        str(image_dir),
        "--output",
        str(predictions_output),
    ]
    print(f"$ {' '.join(command)}")
    started_at = time.perf_counter()
    subprocess.run(command, check=True, cwd=submission_dir)
    return time.perf_counter() - started_at


def evaluate_predictions(
    annotations_path: Path,
    split_path: Path | None,
    split_name: str,
    predictions: list[dict],
    iou_threshold: float,
) -> dict:
    coco = load_json(annotations_path)
    selected_image_ids = load_selected_image_ids(coco, split_path, split_name)
    filtered_predictions = [prediction for prediction in predictions if int(prediction["image_id"]) in selected_image_ids]
    gt_by_image = build_ground_truth(coco, selected_image_ids)

    detection_ap = evaluate_detection(filtered_predictions, gt_by_image, iou_threshold)
    classification_summary = evaluate_classification(
        predictions=filtered_predictions,
        gt_by_image=gt_by_image,
        category_ids=category_id_list(coco),
        iou_threshold=iou_threshold,
    )
    combined_score = (0.7 * detection_ap) + (0.3 * classification_summary["mAP"])
    return {
        "image_count": len(selected_image_ids),
        "prediction_count": len(filtered_predictions),
        "detection_ap50": round(detection_ap, 6),
        "classification_map50": round(classification_summary["mAP"], 6),
        "combined_score": round(combined_score, 6),
        "evaluated_classes": classification_summary["evaluated_classes"],
        "per_class_ap50": classification_summary["per_class_ap"],
    }


def preflight_submission(submission_dir: Path, image_dir: Path, output_zip: Path, fail_on_empty: bool) -> None:
    scripts_dir = Path(__file__).resolve().parent
    command = [
        sys.executable,
        str(scripts_dir / "preflight_submission.py"),
        str(submission_dir),
        "--image-dir",
        str(image_dir),
        "--output-zip",
        str(output_zip),
    ]
    if fail_on_empty:
        command.append("--fail-on-empty")
    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True)


def print_result(summary: dict) -> None:
    print(f"run_name={summary['run_name']}")
    print(f"images={summary['image_count']}")
    print(f"predictions={summary['prediction_count']}")
    print(f"detection_ap50={summary['detection_ap50']:.6f}")
    print(f"classification_map50={summary['classification_map50']:.6f}")
    print(f"combined_score={summary['combined_score']:.6f}")
    print(f"average_inference_seconds={summary['average_inference_seconds']:.6f}")
    print(f"staged_weight_size_bytes={summary['staged_weight_size_bytes']}")
    if "output_zip_size_bytes" in summary:
        print(f"output_zip_size_bytes={summary['output_zip_size_bytes']}")


if __name__ == "__main__":
    main()
