from __future__ import annotations

import argparse
from pathlib import Path

ALLOWED_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".cfg", ".pt", ".pth", ".onnx", ".safetensors", ".npy"}
WEIGHT_EXTENSIONS = {".pt", ".pth", ".onnx", ".safetensors", ".npy"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the NorgesGruppen submission folder.")
    parser.add_argument("submission_dir", type=Path, help="Directory that will become the zip root.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    submission_dir = args.submission_dir.resolve()
    if not submission_dir.exists():
        raise SystemExit(f"Missing directory: {submission_dir}")

    files = sorted(path for path in submission_dir.rglob("*") if path.is_file())
    relative_names = [path.relative_to(submission_dir).as_posix() for path in files]

    errors: list[str] = []
    if "run.py" not in relative_names:
        errors.append("run.py must exist at the zip root.")

    if len(files) > 1000:
        errors.append(f"Too many files: {len(files)} > 1000")

    python_files = [path for path in files if path.suffix == ".py"]
    if len(python_files) > 10:
        errors.append(f"Too many Python files: {len(python_files)} > 10")

    weights = [path for path in files if path.suffix in WEIGHT_EXTENSIONS]
    if len(weights) > 3:
        errors.append(f"Too many weight files: {len(weights)} > 3")

    total_weight_size = sum(path.stat().st_size for path in weights)
    max_bytes = 420 * 1024 * 1024
    if total_weight_size > max_bytes:
        errors.append(f"Weight files total {total_weight_size} bytes, above 420 MB.")

    for path in files:
        if path.suffix not in ALLOWED_EXTENSIONS:
            errors.append(f"Disallowed file type: {path.relative_to(submission_dir).as_posix()}")

    total_size = sum(path.stat().st_size for path in files)
    if total_size > max_bytes:
        errors.append(f"Directory totals {total_size} bytes, above 420 MB.")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    print(f"OK: {submission_dir}")
    print(f"files={len(files)} python_files={len(python_files)} weight_files={len(weights)} total_bytes={total_size}")


if __name__ == "__main__":
    main()
