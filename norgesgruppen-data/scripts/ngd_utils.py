from __future__ import annotations

import json
import random
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def sort_categories(coco: dict) -> list[dict]:
    return sorted(coco.get("categories", []), key=lambda category: int(category["id"]))


def class_index_by_category_id(coco: dict) -> dict[int, int]:
    return {int(category["id"]): index for index, category in enumerate(sort_categories(coco))}


def category_id_list(coco: dict) -> list[int]:
    return [int(category["id"]) for category in sort_categories(coco)]


def category_name_by_id(coco: dict) -> dict[int, str]:
    return {int(category["id"]): str(category.get("name", category["id"])) for category in coco.get("categories", [])}


def annotations_by_image_id(coco: dict) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for annotation in coco.get("annotations", []):
        image_id = int(annotation["image_id"])
        grouped.setdefault(image_id, []).append(annotation)
    return grouped


def image_records_by_id(coco: dict) -> dict[int, dict]:
    return {int(image["id"]): image for image in coco.get("images", [])}


def infer_group(file_name: str, image_record: dict | None = None) -> str:
    path = Path(file_name)
    if len(path.parts) > 1:
        return path.parts[0]
    if image_record and image_record.get("section"):
        return str(image_record["section"])
    stem = path.stem
    stem_parts = stem.split("_")
    if len(stem_parts) > 1 and stem_parts[0].lower() not in {"img", "image"}:
        return stem_parts[0]
    return "ungrouped"


def resolve_image_path(images_dir: Path, file_name: str) -> Path:
    direct = images_dir / file_name
    if direct.exists():
        return direct
    flat = images_dir / Path(file_name).name
    if flat.exists():
        return flat
    raise FileNotFoundError(f"Unable to resolve image '{file_name}' under {images_dir}")


def make_train_val_split(coco: dict, val_fraction: float, seed: int, group_mode: str = "auto") -> dict:
    images = [dict(image) for image in coco.get("images", [])]
    if not images:
        raise ValueError("annotations.json contains no images")

    group_mode = group_mode.lower()
    rng = random.Random(seed)
    for image in images:
        image["group"] = infer_group(str(image.get("file_name", "")), image)

    if group_mode == "random":
        return split_random(images, val_fraction, rng)

    unique_groups = {image["group"] for image in images}
    if group_mode == "auto" and len(unique_groups) <= 1:
        return split_random(images, val_fraction, rng)

    if group_mode not in {"auto", "group"}:
        raise ValueError(f"Unsupported group_mode: {group_mode}")

    groups: dict[str, list[dict]] = {}
    for image in images:
        groups.setdefault(image["group"], []).append(image)

    target_val = max(1, int(round(len(images) * val_fraction)))
    ordered_groups = list(groups.items())
    rng.shuffle(ordered_groups)
    ordered_groups.sort(key=lambda item: len(item[1]), reverse=True)

    val_ids: list[int] = []
    train_ids: list[int] = []
    current_val = 0
    for _, group_images in ordered_groups:
        group_ids = [int(image["id"]) for image in group_images]
        if current_val < target_val:
            val_ids.extend(group_ids)
            current_val += len(group_ids)
        else:
            train_ids.extend(group_ids)

    if not train_ids or not val_ids:
        return split_random(images, val_fraction, rng)

    return {
        "train_image_ids": sorted(train_ids),
        "val_image_ids": sorted(val_ids),
    }


def split_random(images: list[dict], val_fraction: float, rng: random.Random) -> dict:
    image_ids = [int(image["id"]) for image in images]
    rng.shuffle(image_ids)
    val_count = min(len(image_ids) - 1, max(1, int(round(len(image_ids) * val_fraction))))
    val_ids = sorted(image_ids[:val_count])
    train_ids = sorted(image_ids[val_count:])
    if not train_ids:
        raise ValueError("Split would leave zero training images")
    return {
        "train_image_ids": train_ids,
        "val_image_ids": val_ids,
    }
