from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a submission zip with run.py at the archive root.")
    parser.add_argument("submission_dir", type=Path, help="Directory whose contents should become the zip root.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/submission.zip"),
        help="Output zip path. Defaults to dist/submission.zip",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    submission_dir = args.submission_dir.resolve()
    output_path = args.output.resolve()
    if not submission_dir.exists():
        raise SystemExit(f"Missing submission directory: {submission_dir}")

    files = collect_files(submission_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.relative_to(submission_dir).as_posix())

    print(f"OK: {output_path}")
    print(f"files={len(files)}")


def collect_files(submission_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(submission_dir.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(submission_dir).parts
        if should_skip(relative_parts):
            continue
        files.append(path)
    return files


def should_skip(parts: tuple[str, ...]) -> bool:
    for part in parts:
        if part == "__MACOSX":
            return True
        if part == "__pycache__":
            return True
        if part.startswith("."):
            return True
    return False


if __name__ == "__main__":
    main()
