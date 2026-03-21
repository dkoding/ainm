from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import infer_group, load_json, save_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create repeated image-level or group-level cross-validation splits.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/splits/cv/default"),
        help="Directory where fold split files and the manifest should be written.",
    )
    parser.add_argument("--fold-count", type=int, default=3, help="Number of folds per repeat.")
    parser.add_argument("--repeats", type=int, default=1, help="Number of independent repeated fold assignments.")
    parser.add_argument("--seed", type=int, default=42, help="Base RNG seed.")
    parser.add_argument(
        "--group-mode",
        choices=("auto", "group", "random"),
        default="auto",
        help="Whether to keep inferred image groups together across folds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.fold_count < 2:
        raise SystemExit("--fold-count must be at least 2")
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")

    annotations_path = args.annotations.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    coco = load_json(annotations_path)

    images = [dict(image) for image in coco.get("images", [])]
    if len(images) < args.fold_count:
        raise SystemExit(f"Need at least {args.fold_count} images to create {args.fold_count} folds")

    groups = build_groups(images=images, group_mode=args.group_mode)
    if len(groups) < args.fold_count:
        raise SystemExit(
            f"Unable to create {args.fold_count} folds from only {len(groups)} group buckets. "
            "Use --group-mode random or reduce --fold-count."
        )

    split_entries: list[dict] = []
    for repeat_index in range(args.repeats):
        repeat_seed = args.seed + repeat_index
        fold_groups = assign_groups_to_folds(
            groups=groups,
            fold_count=args.fold_count,
            rng=random.Random(repeat_seed),
        )
        for fold_index, val_groups in enumerate(fold_groups):
            val_image_ids = sorted(image_id for group in val_groups for image_id in group)
            val_id_set = set(val_image_ids)
            train_image_ids = sorted(
                int(image["id"])
                for image in images
                if int(image["id"]) not in val_id_set
            )
            if not train_image_ids or not val_image_ids:
                raise SystemExit(f"Invalid fold assignment for repeat={repeat_index + 1} fold={fold_index + 1}")

            relative_path = Path(f"repeat_{repeat_index + 1:02d}") / f"fold_{fold_index + 1:02d}.json"
            split_path = output_dir / relative_path
            payload = {
                "annotations_path": str(annotations_path),
                "repeat_index": repeat_index + 1,
                "repeat_seed": repeat_seed,
                "fold_index": fold_index + 1,
                "fold_count": args.fold_count,
                "group_mode": args.group_mode,
                "train_image_ids": train_image_ids,
                "val_image_ids": val_image_ids,
            }
            save_json(split_path, payload)
            split_entries.append(
                {
                    "path": relative_path.as_posix(),
                    "repeat_index": repeat_index + 1,
                    "fold_index": fold_index + 1,
                    "train_image_count": len(train_image_ids),
                    "val_image_count": len(val_image_ids),
                }
            )

    manifest = {
        "annotations_path": str(annotations_path),
        "seed": args.seed,
        "repeats": args.repeats,
        "fold_count": args.fold_count,
        "group_mode": args.group_mode,
        "split_count": len(split_entries),
        "splits": split_entries,
    }
    manifest_path = output_dir / "manifest.json"
    save_json(manifest_path, manifest)

    print(f"manifest={manifest_path}")
    print(f"split_count={len(split_entries)}")
    print(f"group_bucket_count={len(groups)}")


def build_groups(images: list[dict], group_mode: str) -> list[list[int]]:
    if group_mode == "random":
        return [[int(image["id"])] for image in images]

    grouped: dict[str, list[int]] = {}
    for image in images:
        group = infer_group(str(image.get("file_name", "")), image)
        grouped.setdefault(group, []).append(int(image["id"]))

    if group_mode == "auto" and len(grouped) <= 1:
        return [[int(image["id"])] for image in images]

    return [sorted(image_ids) for _, image_ids in sorted(grouped.items())]


def assign_groups_to_folds(groups: list[list[int]], fold_count: int, rng: random.Random) -> list[list[list[int]]]:
    ordered = [list(group) for group in groups]
    rng.shuffle(ordered)
    ordered.sort(key=len, reverse=True)

    fold_groups: list[list[list[int]]] = [[] for _ in range(fold_count)]
    fold_sizes = [0] * fold_count
    for group in ordered:
        destination = min(range(fold_count), key=lambda index: (fold_sizes[index], index))
        fold_groups[destination].append(group)
        fold_sizes[destination] += len(group)
    return fold_groups


if __name__ == "__main__":
    main()
