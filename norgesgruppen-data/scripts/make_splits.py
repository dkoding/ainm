from __future__ import annotations

import argparse
from pathlib import Path

from ngd_utils import load_json, make_train_val_split, save_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create reproducible train/validation splits.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/splits/default_split.json"),
        help="Where to write the split JSON.",
    )
    parser.add_argument("--val-fraction", type=float, default=0.2, help="Validation fraction.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--group-mode",
        choices=("auto", "group", "random"),
        default="auto",
        help="Whether to split by inferred groups or by image.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coco = load_json(args.annotations.resolve())
    split = make_train_val_split(
        coco=coco,
        val_fraction=args.val_fraction,
        seed=args.seed,
        group_mode=args.group_mode,
    )
    payload = {
        "annotations_path": str(args.annotations.resolve()),
        "seed": args.seed,
        "val_fraction": args.val_fraction,
        "group_mode": args.group_mode,
        "train_image_ids": split["train_image_ids"],
        "val_image_ids": split["val_image_ids"],
    }
    save_json(args.output.resolve(), payload)
    print(f"OK: {args.output.resolve()}")
    print(f"train_images={len(split['train_image_ids'])} val_images={len(split['val_image_ids'])}")


if __name__ == "__main__":
    main()
