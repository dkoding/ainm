from __future__ import annotations

import argparse
import csv
import shutil
import sys
import unicodedata
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import (
    annotations_by_image_id,
    class_index_by_category_id,
    load_json,
    make_train_val_split,
    resolve_image_path,
    save_json,
    sort_categories,
)

PROJECT_ROOT = SCRIPTS_DIR.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare YOLO training data and optionally launch training.")
    parser.add_argument("annotations", type=Path, help="Path to annotations.json")
    parser.add_argument("images_dir", type=Path, help="Directory containing the shelf images")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("data/processed/yolov8"),
        help="Workspace for prepared YOLO data and metadata.",
    )
    parser.add_argument("--split", type=Path, help="Optional split JSON. If omitted, one is generated on the fly.")
    parser.add_argument("--val-fraction", type=float, default=0.2, help="Validation fraction for auto splits.")
    parser.add_argument("--seed", type=int, default=42, help="Seed for auto splits.")
    parser.add_argument("--group-mode", choices=("auto", "group", "random"), default="auto")
    parser.add_argument("--model", default="yolov8m.pt", help="Ultralytics model spec to fine-tune.")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="0", help="Ultralytics device argument.")
    parser.add_argument("--project", default="runs/ngd")
    parser.add_argument("--name", default="yolov8-baseline")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--close-mosaic", type=int, default=10, help="Disable mosaic this many epochs before the end.")
    parser.add_argument("--patience", type=int, default=20, help="Stop after this many epochs without validation improvement.")
    parser.add_argument("--single-cls", action="store_true", help="Train as a single-class detector.")
    parser.add_argument("--cache", action="store_true", help="Enable Ultralytics dataset caching.")
    parser.add_argument("--exist-ok", action="store_true", help="Allow reusing an existing Ultralytics run directory.")
    parser.add_argument("--disable-amp", action="store_true", help="Disable Automatic Mixed Precision.")
    parser.add_argument("--prepare-only", action="store_true", help="Only prepare the YOLO dataset layout.")
    parser.add_argument("--clean", action="store_true", help="Delete the workspace before preparing data.")
    parser.add_argument(
        "--submission-dir",
        type=Path,
        help="Optional submission directory to receive the generated class_map.json.",
    )
    parser.add_argument("--copy-images", action="store_true", help="Copy images instead of hardlinking them.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coco = load_json(args.annotations.resolve())
    images_dir = args.images_dir.resolve()
    workspace = args.workspace.resolve()

    if args.clean and workspace.exists():
        shutil.rmtree(workspace)

    split = load_split(args, coco)
    prepared = prepare_workspace(coco, images_dir, workspace, split, copy_images=args.copy_images)
    if args.submission_dir:
        destination = args.submission_dir.resolve() / "class_map.json"
        destination.write_text(prepared["class_map_path"].read_text(encoding="utf-8"), encoding="utf-8")

    print(f"dataset_yaml={prepared['dataset_yaml_path']}")
    print(f"class_map={prepared['class_map_path']}")
    print(f"train_images={prepared['train_image_count']} val_images={prepared['val_image_count']}")

    if args.prepare_only:
        return

    try:
        add_local_ultralytics_path()
        patch_torch_load_for_ultralytics()
        from ultralytics import YOLO
        patch_ultralytics_threadpool()
        patch_ultralytics_results_reader()
        disable_ultralytics_integration_callbacks()
    except ImportError as exc:
        raise SystemExit("ultralytics is required to launch training. Re-run with --prepare-only if needed.") from exc

    model = YOLO(args.model)
    project = Path(args.project)
    if not project.is_absolute():
        project = project.resolve()
    model.train(
        data=str(prepared["dataset_yaml_path"]),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(project),
        name=args.name,
        workers=args.workers,
        close_mosaic=args.close_mosaic,
        patience=args.patience,
        single_cls=args.single_cls,
        cache=args.cache,
        exist_ok=args.exist_ok,
        amp=not args.disable_amp,
        plots=False,
    )


def patch_torch_load_for_ultralytics() -> None:
    import torch

    original_load = torch.load
    if getattr(original_load, "_ngd_force_weights_only_false", False):
        return

    def patched_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    patched_load._ngd_force_weights_only_false = True
    torch.load = patched_load


def load_split(args: argparse.Namespace, coco: dict) -> dict:
    if args.split:
        split = load_json(args.split.resolve())
        return {
            "train_image_ids": [int(image_id) for image_id in split["train_image_ids"]],
            "val_image_ids": [int(image_id) for image_id in split["val_image_ids"]],
        }
    return make_train_val_split(coco, val_fraction=args.val_fraction, seed=args.seed, group_mode=args.group_mode)


def prepare_workspace(
    coco: dict,
    images_dir: Path,
    workspace: Path,
    split: dict,
    copy_images: bool,
) -> dict:
    categories = sort_categories(coco)
    class_index = class_index_by_category_id(coco)
    annotations_by_image = annotations_by_image_id(coco)
    images_by_id = {int(image["id"]): image for image in coco.get("images", [])}

    train_ids = {int(image_id) for image_id in split["train_image_ids"]}
    val_ids = {int(image_id) for image_id in split["val_image_ids"]}
    if train_ids & val_ids:
        raise ValueError("Train/val split contains overlapping image IDs")

    for split_name in ("train", "val"):
        (workspace / split_name / "images").mkdir(parents=True, exist_ok=True)
        (workspace / split_name / "labels").mkdir(parents=True, exist_ok=True)

    for image_id, image in images_by_id.items():
        if image_id in train_ids:
            split_name = "train"
        elif image_id in val_ids:
            split_name = "val"
        else:
            continue

        source_path = resolve_image_path(images_dir, str(image["file_name"]))
        destination_image = workspace / split_name / "images" / Path(str(image["file_name"])).name
        link_or_copy(source_path, destination_image, copy_images=copy_images)
        label_path = workspace / split_name / "labels" / f"{destination_image.stem}.txt"
        write_yolo_labels(
            label_path=label_path,
            annotations=annotations_by_image.get(image_id, []),
            image_width=float(image["width"]),
            image_height=float(image["height"]),
            class_index_by_category=class_index,
        )

    dataset_yaml_path = workspace / "dataset.yaml"
    write_dataset_yaml(dataset_yaml_path, workspace, categories)
    class_map_path = workspace / "class_map.json"
    save_json(class_map_path, [int(category["id"]) for category in categories])
    save_json(
        workspace / "split.json",
        {
            "train_image_ids": sorted(train_ids),
            "val_image_ids": sorted(val_ids),
        },
    )

    return {
        "dataset_yaml_path": dataset_yaml_path,
        "class_map_path": class_map_path,
        "train_image_count": len(train_ids),
        "val_image_count": len(val_ids),
    }


def add_local_ultralytics_path() -> None:
    for root in (PROJECT_ROOT, PROJECT_ROOT.parent):
        for folder_name in (".vendor_ultra",):
            candidate = root / folder_name
            if candidate.exists() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))


def patch_ultralytics_threadpool() -> None:
    from concurrent.futures import ThreadPoolExecutor

    import ultralytics.data.dataset as dataset_module

    class SafeThreadPool:
        def __init__(self, processes: int):
            self.processes = max(1, int(processes))
            self.executor = None

        def __enter__(self):
            self.executor = ThreadPoolExecutor(max_workers=self.processes)
            return self

        def __exit__(self, exc_type, exc, tb):
            if self.executor is not None:
                self.executor.shutdown(wait=True)
                self.executor = None
            return False

        def imap(self, func, iterable):
            if self.executor is None:
                raise RuntimeError("SafeThreadPool executor is not initialized")
            return self.executor.map(func, iterable)

    dataset_module.ThreadPool = SafeThreadPool


def patch_ultralytics_results_reader() -> None:
    import ultralytics.engine.trainer as trainer_module

    if getattr(trainer_module.BaseTrainer.read_results_csv, "_ngd_csv_patch", False):
        return

    def read_results_csv(self):
        if not self.csv.exists():
            return {}
        try:
            with self.csv.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                columns: dict[str, list[float | str]] = {}
                for row in reader:
                    for key, value in row.items():
                        columns.setdefault(key, []).append(_coerce_csv_value(value))
                return columns
        except Exception:
            return {}

    read_results_csv._ngd_csv_patch = True
    trainer_module.BaseTrainer.read_results_csv = read_results_csv


def disable_ultralytics_integration_callbacks() -> None:
    import ultralytics.utils.callbacks as callbacks_module

    if getattr(callbacks_module.add_integration_callbacks, "_ngd_disabled", False):
        return

    def disabled_add_integration_callbacks(*args, **kwargs):
        return None

    disabled_add_integration_callbacks._ngd_disabled = True
    callbacks_module.add_integration_callbacks = disabled_add_integration_callbacks


def _coerce_csv_value(value: str | None) -> float | str:
    if value is None:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        return float(stripped)
    except ValueError:
        return stripped


def link_or_copy(source_path: Path, destination_path: Path, copy_images: bool) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        destination_path.unlink()
    if copy_images:
        shutil.copy2(source_path, destination_path)
        return
    try:
        destination_path.hardlink_to(source_path)
    except OSError:
        shutil.copy2(source_path, destination_path)


def write_yolo_labels(
    label_path: Path,
    annotations: list[dict],
    image_width: float,
    image_height: float,
    class_index_by_category: dict[int, int],
) -> None:
    lines = []
    for annotation in annotations:
        bbox = annotation.get("bbox", [0, 0, 0, 0])
        if len(bbox) != 4 or bbox[2] <= 0 or bbox[3] <= 0:
            continue
        category_id = int(annotation["category_id"])
        class_id = class_index_by_category[category_id]
        x, y, width, height = [float(value) for value in bbox]
        x_center = (x + (width / 2.0)) / image_width
        y_center = (y + (height / 2.0)) / image_height
        norm_width = width / image_width
        norm_height = height / image_height
        lines.append(f"{class_id} {x_center:.8f} {y_center:.8f} {norm_width:.8f} {norm_height:.8f}")
    label_path.write_text("\n".join(lines), encoding="utf-8")


def normalize_dataset_name(value: str, index: int) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.replace("'", "''").strip()
    return normalized or f"class_{index}"


def write_dataset_yaml(dataset_yaml_path: Path, workspace: Path, categories: list[dict]) -> None:
    lines = [
        f"path: {workspace.as_posix()}",
        "train: train/images",
        "val: val/images",
        "names:",
    ]
    for index, category in enumerate(categories):
        name = normalize_dataset_name(str(category.get("name", index)), index)
        lines.append(f"  {index}: '{name}'")
    dataset_yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
