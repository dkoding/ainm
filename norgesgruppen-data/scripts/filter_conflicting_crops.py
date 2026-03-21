from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import load_json, save_json


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove ambiguous training crops caused by cross-category overlaps or exact duplicate files."
    )
    parser.add_argument("manifest", type=Path, help="Crop manifest JSON produced by extract_product_crops.py")
    parser.add_argument(
        "--filtered-root",
        type=Path,
        default=Path("data/crops/next_run/train_by_category_deduped"),
        help="Output ImageFolder-style root with conflicting crops removed.",
    )
    parser.add_argument(
        "--filtered-manifest",
        type=Path,
        default=Path("data/crops/next_run/train_crop_manifest_deduped.json"),
        help="Where to write the kept-manifest JSON.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/next_run/train_crop_conflicts.json"),
        help="Where to write the conflict report JSON.",
    )
    parser.add_argument(
        "--overlap-iou",
        type=float,
        default=0.85,
        help="Flag different-category annotations from the same image when their bbox IoU meets this threshold.",
    )
    parser.add_argument(
        "--copy-files",
        action="store_true",
        help="Copy files into the filtered root instead of hardlinking when possible.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    filtered_root = args.filtered_root.resolve()
    filtered_manifest_path = args.filtered_manifest.resolve()
    report_path = args.report.resolve()

    manifest = load_json(manifest_path)
    if not isinstance(manifest, list):
        raise SystemExit(f"Manifest must be a JSON array: {manifest_path}")
    entries = [normalize_entry(entry) for entry in manifest]
    entries = [entry for entry in entries if entry["crop_path"].is_file()]
    if not entries:
        raise SystemExit(f"No usable crop files found in {manifest_path}")

    flagged_annotation_ids, overlap_pairs, exact_duplicate_groups = flag_conflicts(
        entries=entries,
        overlap_iou=args.overlap_iou,
    )
    kept_entries = [entry for entry in entries if entry["annotation_id"] not in flagged_annotation_ids]
    flagged_entries = [entry for entry in entries if entry["annotation_id"] in flagged_annotation_ids]
    filtered_root = materialize_filtered_root(
        kept_entries=kept_entries,
        filtered_root=filtered_root,
        copy_files=args.copy_files,
    )

    save_json(filtered_manifest_path, [entry["manifest_entry"] for entry in kept_entries])
    reason_counts = Counter(
        reason
        for entry in flagged_entries
        for reason in entry.get("flag_reasons", [])
    )
    report = {
        "manifest": str(manifest_path),
        "settings": {
            "overlap_iou": args.overlap_iou,
            "copy_files": bool(args.copy_files),
        },
        "summary": {
            "input_crop_count": len(entries),
            "kept_crop_count": len(kept_entries),
            "flagged_crop_count": len(flagged_entries),
            "flagged_fraction": round(len(flagged_entries) / max(1, len(entries)), 6),
            "overlap_pair_count": len(overlap_pairs),
            "exact_duplicate_group_count": len(exact_duplicate_groups),
            "flag_reason_counts": dict(reason_counts),
            "filtered_root": str(filtered_root),
            "filtered_manifest": str(filtered_manifest_path),
        },
        "overlap_pairs": overlap_pairs,
        "exact_duplicate_groups": exact_duplicate_groups,
        "flagged": [
            {
                "annotation_id": entry["annotation_id"],
                "image_id": entry["image_id"],
                "category_id": entry["category_id"],
                "source_file": entry["source_file"],
                "crop_file": entry["crop_path"].as_posix(),
                "flag_reasons": list(entry.get("flag_reasons", [])),
            }
            for entry in flagged_entries
        ],
    }
    save_json(report_path, report)

    print(f"report={report_path}")
    print(f"filtered_root={filtered_root}")
    print(f"filtered_manifest={filtered_manifest_path}")
    print(f"input_crops={len(entries)}")
    print(f"flagged_crops={len(flagged_entries)}")
    print(f"kept_crops={len(kept_entries)}")


def normalize_entry(entry: dict) -> dict:
    crop_path = Path(str(entry["crop_file"])).resolve()
    bbox = [float(value) for value in entry.get("bbox", [0, 0, 0, 0])]
    return {
        "manifest_entry": dict(entry),
        "annotation_id": int(entry["annotation_id"]),
        "category_id": int(entry["category_id"]),
        "image_id": int(entry["image_id"]),
        "source_file": str(entry.get("source_file", "")),
        "crop_path": crop_path,
        "bbox": bbox,
        "flag_reasons": [],
    }


def flag_conflicts(
    entries: list[dict],
    overlap_iou: float,
) -> tuple[set[int], list[dict], list[dict]]:
    flagged_annotation_ids: set[int] = set()
    by_image: dict[int, list[int]] = defaultdict(list)
    by_sha1: dict[str, list[int]] = defaultdict(list)
    overlap_pairs: list[dict] = []
    exact_duplicate_groups: list[dict] = []

    for index, entry in enumerate(entries):
        by_image[entry["image_id"]].append(index)
        by_sha1[sha1_path(entry["crop_path"])].append(index)

    for image_id, indices in sorted(by_image.items()):
        for offset, left_index in enumerate(indices):
            left = entries[left_index]
            for right_index in indices[offset + 1 :]:
                right = entries[right_index]
                if left["category_id"] == right["category_id"]:
                    continue
                iou = bbox_iou(left["bbox"], right["bbox"])
                if iou < overlap_iou:
                    continue
                left["flag_reasons"].append("overlap_conflict")
                right["flag_reasons"].append("overlap_conflict")
                flagged_annotation_ids.add(left["annotation_id"])
                flagged_annotation_ids.add(right["annotation_id"])
                overlap_pairs.append(
                    {
                        "image_id": image_id,
                        "iou": round(iou, 6),
                        "left_annotation_id": left["annotation_id"],
                        "left_category_id": left["category_id"],
                        "left_crop_file": left["crop_path"].as_posix(),
                        "right_annotation_id": right["annotation_id"],
                        "right_category_id": right["category_id"],
                        "right_crop_file": right["crop_path"].as_posix(),
                    }
                )

    for digest, indices in sorted(by_sha1.items()):
        if len(indices) <= 1:
            continue
        categories = sorted({entries[index]["category_id"] for index in indices})
        if len(categories) <= 1:
            continue
        for index in indices:
            entries[index]["flag_reasons"].append("exact_duplicate_conflict")
            flagged_annotation_ids.add(entries[index]["annotation_id"])
        exact_duplicate_groups.append(
            {
                "sha1": digest,
                "categories": categories,
                "crop_count": len(indices),
                "entries": [
                    {
                        "annotation_id": entries[index]["annotation_id"],
                        "category_id": entries[index]["category_id"],
                        "image_id": entries[index]["image_id"],
                        "crop_file": entries[index]["crop_path"].as_posix(),
                    }
                    for index in indices
                ],
            }
        )

    for entry in entries:
        entry["flag_reasons"] = sorted(set(entry["flag_reasons"]))

    return flagged_annotation_ids, overlap_pairs, exact_duplicate_groups


def sha1_path(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def bbox_iou(left: list[float], right: list[float]) -> float:
    left_x1, left_y1, left_w, left_h = left
    right_x1, right_y1, right_w, right_h = right
    left_x2 = left_x1 + max(0.0, left_w)
    left_y2 = left_y1 + max(0.0, left_h)
    right_x2 = right_x1 + max(0.0, right_w)
    right_y2 = right_y1 + max(0.0, right_h)

    inter_x1 = max(left_x1, right_x1)
    inter_y1 = max(left_y1, right_y1)
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0

    left_area = max(0.0, left_w) * max(0.0, left_h)
    right_area = max(0.0, right_w) * max(0.0, right_h)
    union_area = left_area + right_area - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def materialize_filtered_root(
    kept_entries: list[dict],
    filtered_root: Path,
    copy_files: bool,
) -> Path:
    if filtered_root.exists():
        shutil.rmtree(filtered_root)
    filtered_root.mkdir(parents=True, exist_ok=True)

    for entry in kept_entries:
        source_path = entry["crop_path"]
        if source_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        destination = filtered_root / str(entry["category_id"]) / source_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        link_or_copy(source_path, destination, copy_files=copy_files)
    return filtered_root


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
