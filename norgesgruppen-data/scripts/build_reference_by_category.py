from __future__ import annotations

import argparse
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import load_json, save_json


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a clean reference_by_category tree from raw reference metadata and images."
    )
    parser.add_argument("annotations", type=Path, help="Path to COCO annotations.json")
    parser.add_argument("reference_dir", type=Path, help="Root directory of the extracted product images dataset")
    parser.add_argument(
        "--metadata",
        type=Path,
        help="Optional metadata path. Defaults to <reference_dir>/metadata.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/crops/next_run/reference_by_category"),
        help="ImageFolder-style output root organized by category_id.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/next_run/reference_by_category_report.json"),
        help="Where to write the rebuild report JSON.",
    )
    parser.add_argument(
        "--preferred-image-type",
        action="append",
        default=["main", "front"],
        help="Preferred reference image stems to keep when available. Repeatable.",
    )
    parser.add_argument(
        "--copy-files",
        action="store_true",
        help="Copy files into the output root instead of hardlinking when possible.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    annotations_path = args.annotations.resolve()
    reference_dir = args.reference_dir.resolve()
    metadata_path = args.metadata.resolve() if args.metadata else reference_dir / "metadata.json"
    output_root = prepare_output_root(args.output_root.resolve())
    report_path = args.report.resolve()

    coco = load_json(annotations_path)
    metadata_entries = normalize_metadata(load_json(metadata_path))
    metadata_by_name: dict[str, list[dict]] = defaultdict(list)
    for entry in metadata_entries.values():
        normalized_name = normalize_name(entry.get("product_name", ""))
        if normalized_name:
            metadata_by_name[normalized_name].append(entry)

    preferred_types = unique_lower(args.preferred_image_type)
    category_reports: list[dict] = []
    output_image_count = 0

    for category in sorted(coco.get("categories", []), key=lambda item: int(item["id"])):
        category_id = int(category["id"])
        category_name = str(category.get("name", category_id))
        matches = sorted(
            metadata_by_name.get(normalize_name(category_name), []),
            key=lambda item: (
                -int(item.get("annotation_count", 0)),
                -len(item.get("image_types", [])),
                str(item.get("product_code", "")),
            ),
        )
        selected_files: list[Path] = []
        selected_codes: list[str] = []

        for match in matches:
            product_code = str(match["product_code"])
            product_dir = reference_dir / product_code
            source_files = select_reference_files(product_dir, preferred_types)
            if not source_files:
                continue
            selected_codes.append(product_code)
            category_dir = output_root / str(category_id)
            category_dir.mkdir(parents=True, exist_ok=True)
            for source_path in source_files:
                destination_path = category_dir / f"{product_code}_{source_path.name}"
                link_or_copy(source_path, destination_path, copy_files=args.copy_files)
                selected_files.append(destination_path)
                output_image_count += 1

        category_reports.append(
            {
                "category_id": category_id,
                "category_name": category_name,
                "matched_product_codes": selected_codes,
                "matched_product_count": len(selected_codes),
                "output_image_count": len(selected_files),
                "preferred_image_types": preferred_types,
                "status": "matched" if selected_codes else "unmatched",
            }
        )

    matched_categories = [entry for entry in category_reports if entry["status"] == "matched"]
    unmatched_categories = [entry for entry in category_reports if entry["status"] == "unmatched"]
    report = {
        "annotations": str(annotations_path),
        "reference_dir": str(reference_dir),
        "metadata": str(metadata_path),
        "output_root": str(output_root),
        "settings": {
            "preferred_image_types": preferred_types,
            "copy_files": bool(args.copy_files),
        },
        "summary": {
            "category_count": len(category_reports),
            "matched_category_count": len(matched_categories),
            "unmatched_category_count": len(unmatched_categories),
            "matched_product_code_count": sum(entry["matched_product_count"] for entry in matched_categories),
            "output_image_count": output_image_count,
        },
        "categories": category_reports,
        "unmatched_categories": [
            {
                "category_id": entry["category_id"],
                "category_name": entry["category_name"],
            }
            for entry in unmatched_categories
        ],
    }
    save_json(report_path, report)

    print(f"output_root={output_root}")
    print(f"report={report_path}")
    print(f"matched_categories={len(matched_categories)}")
    print(f"unmatched_categories={len(unmatched_categories)}")
    print(f"output_images={output_image_count}")


def normalize_metadata(raw) -> dict[str, dict]:
    if isinstance(raw, list):
        normalized = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            product_code = entry.get("product_code") or entry.get("barcode") or entry.get("code") or entry.get("id")
            if product_code is None:
                continue
            normalized[str(product_code)] = dict(entry)
        return normalized

    if isinstance(raw, dict):
        if isinstance(raw.get("products"), list):
            return normalize_metadata(raw["products"])
        normalized = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                normalized[str(key)] = dict(value)
        return normalized

    return {}


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"\s+", " ", text)


def unique_lower(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        lowered = str(value).strip().lower()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(lowered)
    return ordered


def select_reference_files(product_dir: Path, preferred_types: list[str]) -> list[Path]:
    if not product_dir.is_dir():
        return []

    available = [
        path
        for path in sorted(product_dir.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not available:
        return []

    by_stem = {path.stem.lower(): path for path in available}
    selected = [by_stem[image_type] for image_type in preferred_types if image_type in by_stem]
    return selected if selected else available


def prepare_output_root(output_root: Path) -> Path:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def link_or_copy(source_path: Path, destination_path: Path, copy_files: bool) -> None:
    if destination_path.exists():
        destination_path.unlink()
    if copy_files:
        shutil.copy2(source_path, destination_path)
        return
    try:
        destination_path.hardlink_to(source_path)
    except OSError:
        shutil.copy2(source_path, destination_path)


if __name__ == "__main__":
    main()
