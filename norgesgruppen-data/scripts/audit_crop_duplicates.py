from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import load_json, save_json


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit crop manifests for perceptual near-duplicates.")
    parser.add_argument("manifest", type=Path, help="Crop manifest JSON produced by extract_product_crops.py")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/train_crop_duplicate_audit.json"),
        help="Where to write the duplicate audit report JSON.",
    )
    parser.add_argument(
        "--hash-size",
        type=int,
        default=8,
        help="Difference-hash size. 8 yields a 64-bit perceptual hash.",
    )
    parser.add_argument(
        "--hamming-threshold",
        type=int,
        default=4,
        help="Maximum Hamming distance to treat crops as near-duplicates.",
    )
    parser.add_argument(
        "--prefix-bits",
        type=int,
        default=16,
        help="Only compare hashes that share this many leading bits.",
    )
    parser.add_argument(
        "--max-pairs-per-group",
        type=int,
        default=20,
        help="Maximum example pairs to retain per duplicate group in the report.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    report_path = args.report.resolve()

    manifest = load_json(manifest_path)
    if not isinstance(manifest, list):
        raise SystemExit(f"Manifest must be a JSON array: {manifest_path}")

    entries = [normalize_entry(entry) for entry in manifest]
    entries = [entry for entry in entries if entry["crop_path"].is_file()]
    if not entries:
        raise SystemExit(f"No usable crop files found in {manifest_path}")

    hashes = [compute_dhash(entry["crop_path"], hash_size=args.hash_size) for entry in entries]
    duplicate_groups, pair_examples = group_near_duplicates(
        entries=entries,
        hashes=hashes,
        hash_bits=args.hash_size * args.hash_size,
        prefix_bits=args.prefix_bits,
        hamming_threshold=args.hamming_threshold,
        max_pairs_per_group=args.max_pairs_per_group,
    )

    same_category_groups = [group for group in duplicate_groups if group["category_count"] == 1]
    cross_category_groups = [group for group in duplicate_groups if group["category_count"] > 1]
    report = {
        "manifest": str(manifest_path),
        "settings": {
            "hash_size": args.hash_size,
            "hamming_threshold": args.hamming_threshold,
            "prefix_bits": args.prefix_bits,
            "max_pairs_per_group": args.max_pairs_per_group,
        },
        "summary": {
            "input_crop_count": len(entries),
            "duplicate_group_count": len(duplicate_groups),
            "same_category_group_count": len(same_category_groups),
            "cross_category_group_count": len(cross_category_groups),
            "pair_example_count": len(pair_examples),
        },
        "duplicate_groups": duplicate_groups,
        "pair_examples": pair_examples,
    }
    save_json(report_path, report)

    print(f"report={report_path}")
    print(f"duplicate_groups={len(duplicate_groups)}")
    print(f"cross_category_groups={len(cross_category_groups)}")


def normalize_entry(entry: dict) -> dict:
    return {
        "annotation_id": int(entry["annotation_id"]),
        "category_id": int(entry["category_id"]),
        "image_id": int(entry["image_id"]),
        "source_file": str(entry.get("source_file", "")),
        "crop_path": Path(str(entry["crop_file"])).resolve(),
    }


def compute_dhash(path: Path, hash_size: int) -> int:
    from PIL import Image

    image = Image.open(path).convert("L").resize((hash_size + 1, hash_size), Image.Resampling.BILINEAR)
    pixels = list(image.getdata())
    value = 0
    for row in range(hash_size):
        row_offset = row * (hash_size + 1)
        for column in range(hash_size):
            left = pixels[row_offset + column]
            right = pixels[row_offset + column + 1]
            value = (value << 1) | int(left > right)
    return value


def group_near_duplicates(
    entries: list[dict],
    hashes: list[int],
    hash_bits: int,
    prefix_bits: int,
    hamming_threshold: int,
    max_pairs_per_group: int,
) -> tuple[list[dict], list[dict]]:
    buckets: dict[int, list[int]] = defaultdict(list)
    shift = max(0, int(hash_bits) - max(0, int(prefix_bits)))
    for index, hash_value in enumerate(hashes):
        buckets[hash_value >> shift].append(index)

    parent = list(range(len(entries)))
    pair_examples: list[dict] = []

    for indices in buckets.values():
        if len(indices) < 2:
            continue
        for offset, left_index in enumerate(indices):
            for right_index in indices[offset + 1 :]:
                distance = hamming_distance(hashes[left_index], hashes[right_index])
                if distance > hamming_threshold:
                    continue
                union(parent, left_index, right_index)
                if len(pair_examples) < 1000:
                    pair_examples.append(
                        {
                            "left_annotation_id": entries[left_index]["annotation_id"],
                            "left_category_id": entries[left_index]["category_id"],
                            "left_crop_file": entries[left_index]["crop_path"].as_posix(),
                            "right_annotation_id": entries[right_index]["annotation_id"],
                            "right_category_id": entries[right_index]["category_id"],
                            "right_crop_file": entries[right_index]["crop_path"].as_posix(),
                            "hamming_distance": distance,
                        }
                    )

    grouped_indices: dict[int, list[int]] = defaultdict(list)
    for index in range(len(entries)):
        grouped_indices[find(parent, index)].append(index)

    duplicate_groups = []
    for indices in grouped_indices.values():
        if len(indices) < 2:
            continue
        categories = sorted({entries[index]["category_id"] for index in indices})
        group_pairs = [
            example
            for example in pair_examples
            if example["left_annotation_id"] in {entries[index]["annotation_id"] for index in indices}
            and example["right_annotation_id"] in {entries[index]["annotation_id"] for index in indices}
        ][: max_pairs_per_group]
        duplicate_groups.append(
            {
                "crop_count": len(indices),
                "category_count": len(categories),
                "categories": categories,
                "entries": [
                    {
                        "annotation_id": entries[index]["annotation_id"],
                        "category_id": entries[index]["category_id"],
                        "image_id": entries[index]["image_id"],
                        "crop_file": entries[index]["crop_path"].as_posix(),
                    }
                    for index in sorted(indices, key=lambda item: (entries[item]["category_id"], entries[item]["annotation_id"]))
                ],
                "pair_examples": group_pairs,
            }
        )
    duplicate_groups.sort(key=lambda group: (group["category_count"] > 1, group["crop_count"]), reverse=True)
    return duplicate_groups, pair_examples[:1000]


def hamming_distance(left: int, right: int) -> int:
    return int(left ^ right).bit_count()


def find(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def union(parent: list[int], left: int, right: int) -> None:
    left_root = find(parent, left)
    right_root = find(parent, right)
    if left_root == right_root:
        return
    if left_root < right_root:
        parent[right_root] = left_root
    else:
        parent[left_root] = right_root


if __name__ == "__main__":
    main()
