from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import annotations_by_image_id, image_records_by_id, load_json, resolve_image_path, save_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract annotated product crops for classification experiments.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument("images_dir", type=Path, help="Directory containing the shelf images")
    parser.add_argument("output_dir", type=Path, help="Where to write the crops")
    parser.add_argument("--split", type=Path, help="Optional split JSON")
    parser.add_argument("--split-name", choices=("train", "val"), default="train")
    parser.add_argument(
        "--label-key",
        choices=("category_id", "product_code"),
        default="category_id",
        help="Which field to use for crop subdirectories.",
    )
    parser.add_argument("--corrected-only", action="store_true", help="Only include corrected annotations.")
    parser.add_argument("--padding", type=float, default=0.0, help="Extra padding ratio around each bbox.")
    parser.add_argument("--min-size", type=int, default=8, help="Skip crops smaller than this many pixels.")
    parser.add_argument(
        "--pad-to-square",
        action="store_true",
        help="Pad extracted crops onto a square canvas so aspect ratio is preserved for classifier training.",
    )
    parser.add_argument(
        "--square-fill",
        type=int,
        default=114,
        help="RGB fill value used for square padding. Must be in [0, 255].",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/crops/crop_manifest.json"),
        help="Where to write the crop manifest JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_pillow()
    if args.square_fill < 0 or args.square_fill > 255:
        raise SystemExit("--square-fill must be in [0, 255]")
    coco = load_json(args.annotations.resolve())
    split = load_json(args.split.resolve()) if args.split else None
    selected_image_ids = select_image_ids(coco, split, args.split_name)
    images_by_id = image_records_by_id(coco)
    annotations_by_image = annotations_by_image_id(coco)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    for image_id in sorted(selected_image_ids):
        image = images_by_id[image_id]
        image_path = resolve_image_path(args.images_dir.resolve(), str(image["file_name"]))
        manifest.extend(
            extract_from_image(
                image_id=image_id,
                image_path=image_path,
                image_record=image,
                annotations=annotations_by_image.get(image_id, []),
                output_dir=output_dir,
                label_key=args.label_key,
                corrected_only=args.corrected_only,
                padding=args.padding,
                min_size=args.min_size,
                pad_to_square=bool(args.pad_to_square),
                square_fill=max(0, min(255, int(args.square_fill))),
            )
        )

    save_json(args.manifest.resolve(), manifest)
    print(f"OK: {output_dir}")
    print(f"crops={len(manifest)}")


def select_image_ids(coco: dict, split: dict | None, split_name: str) -> set[int]:
    if split is None:
        return {int(image["id"]) for image in coco.get("images", [])}
    key = f"{split_name}_image_ids"
    return {int(image_id) for image_id in split.get(key, [])}


def extract_from_image(
    image_id: int,
    image_path: Path,
    image_record: dict,
    annotations: list[dict],
    output_dir: Path,
    label_key: str,
    corrected_only: bool,
    padding: float,
    min_size: int,
    pad_to_square: bool,
    square_fill: int,
) -> list[dict]:
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    crops = []

    for annotation in annotations:
        if corrected_only and not annotation.get("corrected"):
            continue
        bbox = annotation.get("bbox", [0, 0, 0, 0])
        if len(bbox) != 4:
            continue
        crop_box = padded_box(bbox, width, height, padding)
        crop_width = crop_box[2] - crop_box[0]
        crop_height = crop_box[3] - crop_box[1]
        if crop_width < min_size or crop_height < min_size:
            continue

        label_value = annotation.get(label_key)
        if label_value is None:
            continue

        destination_dir = output_dir / str(label_value)
        destination_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"img_{image_id:05d}_ann_{int(annotation['id']):06d}.jpg"
        destination_path = destination_dir / file_name
        crop_image = image.crop(crop_box)
        square_side = None
        if pad_to_square:
            crop_image = pad_image_to_square(crop_image, square_fill=square_fill)
            square_side = int(crop_image.size[0])
        crop_image.save(destination_path, format="JPEG")
        crops.append(
            {
                "image_id": image_id,
                "annotation_id": int(annotation["id"]),
                "category_id": int(annotation["category_id"]),
                "product_code": annotation.get("product_code"),
                "product_name": annotation.get("product_name"),
                "source_file": str(image_record["file_name"]),
                "crop_file": destination_path.as_posix(),
                "bbox": bbox,
                "crop_box": crop_box,
                "pad_to_square": bool(pad_to_square),
                "square_fill": int(square_fill) if pad_to_square else None,
                "square_side": square_side,
            }
        )

    return crops


def ensure_pillow() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError as exc:
        raise SystemExit("Pillow is required for crop extraction. Install it locally or run this in the sandbox environment.") from exc


def padded_box(bbox, image_width: int, image_height: int, padding: float) -> tuple[int, int, int, int]:
    x, y, width, height = [float(value) for value in bbox]
    pad_w = width * padding
    pad_h = height * padding
    x1 = max(0, int(round(x - pad_w)))
    y1 = max(0, int(round(y - pad_h)))
    x2 = min(image_width, int(round(x + width + pad_w)))
    y2 = min(image_height, int(round(y + height + pad_h)))
    return (x1, y1, x2, y2)


def pad_image_to_square(image, square_fill: int):
    from PIL import Image

    width, height = image.size
    side = max(width, height)
    canvas = Image.new("RGB", (side, side), (square_fill, square_fill, square_fill))
    offset_x = (side - width) // 2
    offset_y = (side - height) // 2
    canvas.paste(image, (offset_x, offset_y))
    return canvas


if __name__ == "__main__":
    main()
