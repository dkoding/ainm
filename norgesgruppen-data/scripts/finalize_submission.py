from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run final local verification and build a submission zip.")
    parser.add_argument(
        "--submission-dir",
        type=Path,
        default=Path("submission"),
        help="Submission directory containing run.py and weights.",
    )
    parser.add_argument(
        "--output-zip",
        type=Path,
        default=Path("dist/submission.zip"),
        help="Where to write the final zip.",
    )
    parser.add_argument("--annotations", type=Path, help="Optional annotations.json for local scoring.")
    parser.add_argument("--image-dir", type=Path, help="Optional image directory for local scoring.")
    parser.add_argument("--split", type=Path, help="Optional split JSON for local scoring.")
    parser.add_argument("--split-name", choices=("train", "val"), default="val")
    parser.add_argument(
        "--predictions-output",
        type=Path,
        default=Path("data/reports/final_submission_predictions.json"),
        help="Where to write local predictions when scoring is enabled.",
    )
    parser.add_argument(
        "--score-output",
        type=Path,
        default=Path("data/reports/final_submission_eval.json"),
        help="Where to write the local score summary when scoring is enabled.",
    )
    parser.add_argument("--fail-on-empty", action="store_true")
    parser.add_argument("--python-executable", type=Path, help="Optional Python interpreter for local scoring.")
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
    submission_dir = args.submission_dir.resolve()
    output_zip = args.output_zip.resolve()

    if args.annotations and args.image_dir:
        command = [
            sys.executable,
            str(SCRIPTS_DIR / "score_submission_run.py"),
            str(args.annotations.resolve()),
            str(args.image_dir.resolve()),
            "--submission-dir",
            str(submission_dir),
            "--predictions-output",
            str(args.predictions_output.resolve()),
            "--output",
            str(args.score_output.resolve()),
            "--output-zip",
            str(output_zip),
            "--split-name",
            args.split_name,
        ]
        if args.split:
            command.extend(["--split", str(args.split.resolve())])
        if args.fail_on_empty:
            command.append("--fail-on-empty")
        if args.python_executable:
            command.extend(["--python-executable", str(args.python_executable.resolve())])
        for path in args.pythonpath:
            command.extend(["--pythonpath", str(path.resolve())])
    else:
        command = [
            sys.executable,
            str(SCRIPTS_DIR / "preflight_submission.py"),
            str(submission_dir),
            "--output-zip",
            str(output_zip),
        ]
        if args.image_dir:
            command.extend(["--image-dir", str(args.image_dir.resolve())])
        if args.fail_on_empty:
            command.append("--fail-on-empty")
        if args.python_executable:
            command.extend(["--python-executable", str(args.python_executable.resolve())])
        for path in args.pythonpath:
            command.extend(["--pythonpath", str(path.resolve())])

    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
