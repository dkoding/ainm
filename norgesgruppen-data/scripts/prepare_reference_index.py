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
    directory_names = sorted(path.name for path in reference_dir.iterdir() if path.is_dir())

    manifest = {}
    for key in sorted(set(metadata) | set(directory_names)):
        product_dir = reference_dir / key
        image_paths = sorted(
            image_path.relative_to(reference_dir).as_posix()
            for image_path in product_dir.iterdir()
            if image_path.is_file() and image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ) if product_dir.is_dir() else []
        manifest[key] = {
            "product_code": key,
            "images": image_paths,
            "metadata": metadata.get(key),
            "in_metadata": key in metadata,
            "has_directory": product_dir.is_dir(),
        }

    payload = {
        "summary": {
            "metadata_product_count": len(metadata),
            "directory_product_count": len(directory_names),
            "manifest_product_count": len(manifest),
            "metadata_without_directory_count": sum(
                1 for key in metadata if key not in directory_names
            ),
            "directory_without_metadata_count": sum(
                1 for key in directory_names if key not in metadata
            ),
        },
        "products": manifest,
    }

    save_json(args.output.resolve(), payload)
    print(f"OK: {args.output.resolve()}")
    print(f"products={len(manifest)}")
    print(
        "metadata_without_directory="
        f"{payload['summary']['metadata_without_directory_count']} "
        "directory_without_metadata="
        f"{payload['summary']['directory_without_metadata_count']}"
    )


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
