from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ngd_utils import annotations_by_image_id, category_name_by_id, image_records_by_id, infer_group, load_json, save_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize the NorgesGruppen COCO dataset.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument("--images-dir", type=Path, help="Optional image root for missing-file checks.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path for the summary.")
    parser.add_argument("--top-k", type=int, default=10, help="How many top categories/product codes to show.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coco = load_json(args.annotations.resolve())
    images_by_id = image_records_by_id(coco)
    annotations_by_image = annotations_by_image_id(coco)
    category_names = category_name_by_id(coco)

    category_counts: Counter[int] = Counter()
    product_code_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    corrected_count = 0
    images_with_annotations = 0

    for image_id, image in images_by_id.items():
        group_counts[infer_group(str(image.get("file_name", "")), image)] += 1
        if annotations_by_image.get(image_id):
            images_with_annotations += 1

    for annotation in coco.get("annotations", []):
        category_id = int(annotation["category_id"])
        category_counts[category_id] += 1
        product_code = str(annotation.get("product_code", "missing"))
        product_code_counts[product_code] += 1
        if annotation.get("corrected"):
            corrected_count += 1

    missing_images: list[str] = []
    if args.images_dir:
        for image in images_by_id.values():
            candidate = args.images_dir.resolve() / str(image["file_name"])
            if not candidate.exists():
                candidate = args.images_dir.resolve() / Path(str(image["file_name"])).name
            if not candidate.exists():
                missing_images.append(str(image["file_name"]))

    summary = {
        "image_count": len(images_by_id),
        "annotation_count": len(coco.get("annotations", [])),
        "category_count": len(coco.get("categories", [])),
        "images_with_annotations": images_with_annotations,
        "corrected_annotation_count": corrected_count,
        "avg_annotations_per_image": round(len(coco.get("annotations", [])) / max(1, len(images_by_id)), 3),
        "group_counts": dict(sorted(group_counts.items())),
        "top_categories": [
            {
                "category_id": category_id,
                "name": category_names.get(category_id, str(category_id)),
                "count": count,
            }
            for category_id, count in category_counts.most_common(args.top_k)
        ],
        "top_product_codes": [
            {"product_code": product_code, "count": count}
            for product_code, count in product_code_counts.most_common(args.top_k)
        ],
        "missing_image_count": len(missing_images),
        "missing_images_sample": missing_images[: min(20, len(missing_images))],
    }

    print_summary(summary)
    if args.output:
        save_json(args.output.resolve(), summary)


def print_summary(summary: dict) -> None:
    print(f"images={summary['image_count']}")
    print(f"annotations={summary['annotation_count']}")
    print(f"categories={summary['category_count']}")
    print(f"images_with_annotations={summary['images_with_annotations']}")
    print(f"corrected_annotations={summary['corrected_annotation_count']}")
    print(f"avg_annotations_per_image={summary['avg_annotations_per_image']}")
    print(f"missing_image_count={summary['missing_image_count']}")
    print("groups=" + ", ".join(f"{name}:{count}" for name, count in summary["group_counts"].items()))
    print(
        "top_categories="
        + ", ".join(
            f"{entry['category_id']}:{entry['count']}" for entry in summary["top_categories"]
        )
    )


if __name__ == "__main__":
    main()
