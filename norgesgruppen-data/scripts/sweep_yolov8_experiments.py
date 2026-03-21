from __future__ import annotations

import argparse
import itertools
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible sweep of YOLOv8 detector experiments.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument("images_dir", type=Path, help="Directory containing the shelf images")
    parser.add_argument("--split", type=Path, help="Optional split JSON used for training and local scoring.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("data/processed/yolov8"),
        help="Workspace for prepared YOLO data.",
    )
    parser.add_argument(
        "--submission-dir",
        type=Path,
        default=Path("submission"),
        help="Submission directory used when exporting class_map.json and optional scoring.",
    )
    parser.add_argument("--models", nargs="+", default=["yolov8s.pt"], help="YOLO model specs to sweep.")
    parser.add_argument("--image-sizes", nargs="+", type=int, default=[960], help="Image sizes to sweep.")
    parser.add_argument("--batches", nargs="+", type=int, default=[16], help="Batch sizes to sweep.")
    parser.add_argument("--epochs", nargs="+", type=int, default=[100], help="Epoch counts to sweep.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--device", default="0")
    parser.add_argument("--project", default="runs/ngd")
    parser.add_argument("--single-cls", action="store_true", help="Train detector as single-class.")
    parser.add_argument("--cache", action="store_true", help="Enable Ultralytics dataset caching.")
    parser.add_argument("--close-mosaic", type=int, default=10)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--exist-ok", action="store_true")
    parser.add_argument("--disable-amp", action="store_true")
    parser.add_argument("--copy-images", action="store_true")
    parser.add_argument("--score-image-dir", type=Path, help="Optional image dir for packaged local scoring after each run.")
    parser.add_argument("--score-split-name", choices=("train", "val"), default="val")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/yolov8_sweep.json"),
        help="Where to write the sweep report JSON.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument(
        "--python-executable",
        type=Path,
        help="Optional Python interpreter for local packaged scoring.",
    )
    parser.add_argument(
        "--pythonpath",
        action="append",
        type=Path,
        default=[],
        help="Optional extra PYTHONPATH entry for local packaged scoring. Repeatable.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    annotations_path = args.annotations.resolve()
    images_dir = args.images_dir.resolve()
    workspace = args.workspace.resolve()
    submission_dir = args.submission_dir.resolve()
    score_image_dir = args.score_image_dir.resolve() if args.score_image_dir else None

    experiment_reports = []
    for model_name, image_size, batch_size, epoch_count in itertools.product(
        args.models,
        args.image_sizes,
        args.batches,
        args.epochs,
    ):
        run_name = make_run_name(
            model_name=model_name,
            image_size=image_size,
            batch_size=batch_size,
            epoch_count=epoch_count,
            single_cls=bool(args.single_cls),
        )
        train_command = [
            sys.executable,
            str(SCRIPTS_DIR / "train_yolov8.py"),
            str(annotations_path),
            str(images_dir),
            "--workspace",
            str(workspace),
            "--submission-dir",
            str(submission_dir),
            "--model",
            model_name,
            "--epochs",
            str(epoch_count),
            "--imgsz",
            str(image_size),
            "--batch",
            str(batch_size),
            "--device",
            str(args.device),
            "--project",
            str(args.project),
            "--name",
            run_name,
            "--workers",
            str(args.workers),
            "--close-mosaic",
            str(args.close_mosaic),
            "--patience",
            str(args.patience),
        ]
        if args.split:
            train_command.extend(["--split", str(args.split.resolve())])
        if args.single_cls:
            train_command.append("--single-cls")
        if args.cache:
            train_command.append("--cache")
        if args.exist_ok:
            train_command.append("--exist-ok")
        if args.disable_amp:
            train_command.append("--disable-amp")
        if args.copy_images:
            train_command.append("--copy-images")

        experiment_report = {
            "run_name": run_name,
            "settings": {
                "model": model_name,
                "imgsz": image_size,
                "batch": batch_size,
                "epochs": epoch_count,
                "workers": args.workers,
                "device": args.device,
                "single_cls": bool(args.single_cls),
            },
            "train_command": train_command,
        }

        print(f"$ {' '.join(train_command)}")
        if not args.dry_run:
            subprocess.run(train_command, check=True)

        if score_image_dir is not None:
            weights_path = Path(args.project).resolve() / run_name / "weights" / "best.pt"
            predictions_output = Path("data/reports") / f"{run_name}_predictions.json"
            score_output = Path("data/reports") / f"{run_name}_eval.json"
            score_command = [
                sys.executable,
                str(SCRIPTS_DIR / "score_submission_run.py"),
                str(annotations_path),
                str(score_image_dir),
                "--submission-dir",
                str(submission_dir),
                "--weights",
                str(weights_path),
                "--predictions-output",
                str(predictions_output),
                "--output",
                str(score_output),
                "--run-name",
                run_name,
                "--split-name",
                args.score_split_name,
            ]
            if args.split:
                score_command.extend(["--split", str(args.split.resolve())])
            if args.python_executable:
                score_command.extend(["--python-executable", str(args.python_executable.resolve())])
            for path in args.pythonpath:
                score_command.extend(["--pythonpath", str(path.resolve())])

            print(f"$ {' '.join(score_command)}")
            if not args.dry_run:
                subprocess.run(score_command, check=True)
            experiment_report["score_output"] = str(score_output.resolve())

        experiment_reports.append(experiment_report)

    report = {
        "annotations_path": str(annotations_path),
        "images_dir": str(images_dir),
        "workspace": str(workspace),
        "submission_dir": str(submission_dir),
        "experiment_count": len(experiment_reports),
        "experiments": experiment_reports,
    }
    args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.report.resolve().write_text(json_dumps(report), encoding="utf-8")
    print(f"report={args.report.resolve()}")


def make_run_name(model_name: str, image_size: int, batch_size: int, epoch_count: int, single_cls: bool) -> str:
    stem = Path(model_name).stem
    mode = "singlecls" if single_cls else "multicls"
    return f"{stem}_{mode}_{image_size}_b{batch_size}_e{epoch_count}"


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
