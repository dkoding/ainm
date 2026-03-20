from __future__ import annotations

import argparse
from pathlib import Path

from ngd_utils import load_json, save_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index product reference images and metadata.")
    parser.add_argument("reference_dir", type=Path, help="Root directory of the extracted product images dataset.")
    parser.add_argument(
        "--metadata",
        type=Path,
        help="Optional path to metadata.json. Defaults to <reference_dir>/metadata.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reference/reference_index.json"),
        help="Output JSON manifest path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reference_dir = args.reference_dir.resolve()
    metadata_path = args.metadata.resolve() if args.metadata else reference_dir / "metadata.json"
    metadata = normalize_metadata(load_json(metadata_path)) if metadata_path.exists() else {}

    manifest = {}
    for product_dir in sorted(path for path in reference_dir.iterdir() if path.is_dir()):
        image_paths = sorted(
            image_path.relative_to(reference_dir).as_posix()
            for image_path in product_dir.iterdir()
            if image_path.is_file() and image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        key = product_dir.name
        manifest[key] = {
            "product_code": key,
            "images": image_paths,
            "metadata": metadata.get(key, {}),
        }

    save_json(args.output.resolve(), manifest)
    print(f"OK: {args.output.resolve()}")
    print(f"products={len(manifest)}")


def normalize_metadata(raw) -> dict[str, dict]:
    if isinstance(raw, list):
        normalized = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            key = entry.get("product_code") or entry.get("barcode") or entry.get("code") or entry.get("id")
            if key is not None:
                normalized[str(key)] = entry
        return normalized

    if isinstance(raw, dict):
        if isinstance(raw.get("products"), list):
            return normalize_metadata(raw["products"])
        normalized = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                normalized[str(key)] = value
        return normalized

    return {}


if __name__ == "__main__":
    main()
