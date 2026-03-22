from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the v2 short-path detector with safe defaults inside the v2 project."
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=PROJECT_ROOT / "data" / "mixed" / "short_path" / "annotations.json",
        help="Merged COCO annotations produced by make_mixed_detector_dataset.py.",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "mixed" / "short_path" / "images",
        help="Merged image directory produced by make_mixed_detector_dataset.py.",
    )
    parser.add_argument(
        "--split",
        type=Path,
        default=PROJECT_ROOT / "data" / "mixed" / "short_path" / "split.json",
        help="Merged split JSON produced by make_mixed_detector_dataset.py.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "yolo26_short_path",
        help="Workspace for prepared YOLO data.",
    )
    parser.add_argument(
        "--submission-dir",
        type=Path,
        default=PROJECT_ROOT / "submission",
        help="v2 submission directory to receive class_map.json.",
    )
    parser.add_argument("--model", default="yolo26n.pt", help="Ultralytics model spec or checkpoint to fine-tune.")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="0")
    parser.add_argument("--project", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument("--name", default="yolo26n_short_path_singlecls")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--close-mosaic", type=int, default=10)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--copy-images", action="store_true")
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--exist-ok", action="store_true")
    parser.add_argument("--disable-amp", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--multi-cls",
        action="store_true",
        help="Disable the short-path default single-class detector mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "train_yolov8.py"),
        str(args.annotations.resolve()),
        str(args.images_dir.resolve()),
        "--split",
        str(args.split.resolve()),
        "--workspace",
        str(args.workspace.resolve()),
        "--submission-dir",
        str(args.submission_dir.resolve()),
        "--model",
        args.model,
        "--epochs",
        str(args.epochs),
        "--imgsz",
        str(args.imgsz),
        "--batch",
        str(args.batch),
        "--device",
        str(args.device),
        "--project",
        str(args.project.resolve()),
        "--name",
        str(args.name),
        "--workers",
        str(args.workers),
        "--close-mosaic",
        str(args.close_mosaic),
        "--patience",
        str(args.patience),
    ]
    if not args.multi_cls:
        command.append("--single-cls")
    if args.copy_images:
        command.append("--copy-images")
    if args.cache:
        command.append("--cache")
    if args.exist_ok:
        command.append("--exist-ok")
    if args.disable_amp:
        command.append("--disable-amp")
    if args.prepare_only:
        command.append("--prepare-only")

    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    main()
