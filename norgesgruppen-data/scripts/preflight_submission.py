from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local validation, smoke testing, and zip creation.")
    parser.add_argument("submission_dir", type=Path, help="Directory containing the submission files.")
    parser.add_argument(
        "--output-zip",
        type=Path,
        default=Path("dist/submission.zip"),
        help="Where to write the built zip.",
    )
    parser.add_argument("--image-dir", type=Path, help="Optional directory of real images for the smoke test.")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip running the local smoke test.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    submission_dir = args.submission_dir.resolve()
    output_zip = args.output_zip.resolve()
    scripts_dir = Path(__file__).resolve().parent

    run_step([sys.executable, str(scripts_dir / "check_submission.py"), str(submission_dir)])

    if not args.skip_smoke:
        smoke_command = [sys.executable, str(scripts_dir / "smoke_submission.py"), str(submission_dir)]
        if args.image_dir:
            smoke_command.extend(["--image-dir", str(args.image_dir.resolve())])
        run_step(smoke_command)

    run_step([sys.executable, str(scripts_dir / "build_submission.py"), str(submission_dir), "--output", str(output_zip)])
    run_step([sys.executable, str(scripts_dir / "check_submission.py"), str(output_zip)])
    print(f"Preflight completed successfully: {output_zip}")


def run_step(command: list[str]) -> None:
    print(f"$ {' '.join(command)}")
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
