from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import load_json, save_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build classifier prototype embeddings for submission-time fusion.")
    parser.add_argument("checkpoint", type=Path, help="Crop-classifier checkpoint used as the embedding backbone.")
    parser.add_argument(
        "--train-manifest",
        type=Path,
        help="Optional crop manifest used to build train-set fallback prototypes.",
    )
    parser.add_argument(
        "--reference-root",
        type=Path,
        help="Optional ImageFolder-style root with clean reference images arranged by category_id.",
    )
    parser.add_argument(
        "--junk-manifest",
        type=Path,
        help="Optional manifest JSON of mined junk negatives to append as a rejector prototype.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("submission/class_prototypes.npy"),
        help="Where to write the prototype matrix .npy file.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/classifier_prototypes.json"),
        help="Where to write the prototype build report JSON.",
    )
    parser.add_argument("--input-size", type=int, default=224, help="Crop size used for embedding extraction.")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default="cuda", help="Torch device string.")
    parser.add_argument(
        "--reference-weight",
        type=float,
        default=0.7,
        help="Blend weight applied when both reference and train prototypes exist.",
    )
    parser.add_argument(
        "--train-weight",
        type=float,
        default=0.3,
        help="Blend weight applied when both reference and train prototypes exist.",
    )
    return parser.parse_args()


def main() -> None:
    from flag_crop_outliers import (
        build_eval_transform,
        extract_embeddings,
        load_embedding_model,
        load_reference_entries,
    )

    args = parse_args()
    checkpoint_path = args.checkpoint.resolve()
    output_path = args.output.resolve()
    report_path = args.report.resolve()

    model, feature_extractor, class_names = load_embedding_model(
        checkpoint_path=checkpoint_path,
        device_name=args.device,
    )
    class_category_ids = [int(name) for name in class_names]
    transform = build_eval_transform(args.input_size)

    train_prototypes = {}
    train_entry_count = 0
    train_global_prototype = None
    if args.train_manifest:
        train_entries = load_manifest_entries(args.train_manifest.resolve(), allowed_category_ids=set(class_category_ids))
        train_entry_count = len(train_entries)
        if train_entries:
            train_embeddings = extract_embeddings(
                model=model,
                feature_extractor=feature_extractor,
                entries=train_entries,
                transform=transform,
                batch_size=args.batch_size,
                workers=args.workers,
            )
            train_prototypes = mean_prototypes_by_category(train_entries, train_embeddings)
            train_global_prototype = normalize_mean(train_embeddings)

    reference_prototypes = {}
    reference_entry_count = 0
    if args.reference_root:
        reference_entries = load_reference_entries(args.reference_root.resolve())
        reference_entries = [entry for entry in reference_entries if entry["category_id"] in set(class_category_ids)]
        reference_entry_count = len(reference_entries)
        if reference_entries:
            reference_embeddings = extract_embeddings(
                model=model,
                feature_extractor=feature_extractor,
                entries=reference_entries,
                transform=transform,
                batch_size=args.batch_size,
                workers=args.workers,
            )
            reference_prototypes = mean_prototypes_by_category(reference_entries, reference_embeddings)

    junk_entries = []
    junk_entry_count = 0
    junk_prototype = None
    if args.junk_manifest:
        junk_entries = load_manifest_entries(args.junk_manifest.resolve(), allowed_category_ids={-2})
        junk_entry_count = len(junk_entries)
        if junk_entries:
            junk_embeddings = extract_embeddings(
                model=model,
                feature_extractor=feature_extractor,
                entries=junk_entries,
                transform=transform,
                batch_size=args.batch_size,
                workers=args.workers,
            )
            junk_prototype = normalize_mean(junk_embeddings)

    rows = []
    category_report = []
    missing_category_ids = []
    for category_id in class_category_ids:
        prototype, source = select_prototype(
            category_id=category_id,
            reference_prototypes=reference_prototypes,
            train_prototypes=train_prototypes,
            reference_weight=args.reference_weight,
            train_weight=args.train_weight,
        )
        if prototype is None:
            missing_category_ids.append(category_id)
            continue
        rows.append(np.concatenate(([float(category_id)], prototype.numpy().astype(np.float32))))
        category_report.append(
            {
                "category_id": category_id,
                "source": source,
                "has_reference_prototype": category_id in reference_prototypes,
                "has_train_prototype": category_id in train_prototypes,
            }
        )

    if missing_category_ids:
        raise SystemExit(f"Missing prototypes for {len(missing_category_ids)} categories: {missing_category_ids[:20]}")

    product_prototype = train_global_prototype
    if product_prototype is not None:
        rows.append(np.concatenate(([-1.0], product_prototype.numpy().astype(np.float32))))
    if junk_prototype is not None:
        rows.append(np.concatenate(([-2.0], junk_prototype.numpy().astype(np.float32))))

    matrix = np.stack(rows).astype(np.float32, copy=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, matrix, allow_pickle=False)

    report = {
        "checkpoint": str(checkpoint_path),
        "output": str(output_path),
        "settings": {
            "input_size": args.input_size,
            "batch_size": args.batch_size,
            "workers": args.workers,
            "device": args.device,
            "reference_weight": args.reference_weight,
            "train_weight": args.train_weight,
        },
        "summary": {
            "category_count": len(class_category_ids),
            "prototype_count": int(matrix.shape[0]),
            "embedding_dim": int(matrix.shape[1] - 1),
            "reference_entry_count": reference_entry_count,
            "train_entry_count": train_entry_count,
            "reference_backed_categories": sum(1 for entry in category_report if entry["has_reference_prototype"]),
            "train_backed_categories": sum(1 for entry in category_report if entry["has_train_prototype"]),
            "junk_entry_count": junk_entry_count,
            "has_product_rejector_prototype": product_prototype is not None,
            "has_junk_rejector_prototype": junk_prototype is not None,
        },
        "categories": category_report,
    }
    save_json(report_path, report)

    print(f"output={output_path}")
    print(f"report={report_path}")
    print(f"prototype_count={matrix.shape[0]}")
    print(f"embedding_dim={matrix.shape[1] - 1}")


def load_manifest_entries(path: Path, allowed_category_ids: set[int]) -> list[dict]:
    from flag_crop_outliers import normalize_entry

    manifest = load_json(path)
    if not isinstance(manifest, list):
        raise SystemExit(f"Manifest must be a JSON array: {path}")
    entries = [normalize_entry(entry) for entry in manifest]
    entries = [entry for entry in entries if entry["crop_path"].is_file() and entry["category_id"] in allowed_category_ids]
    return entries


def mean_prototypes_by_category(entries: list[dict], embeddings) -> dict[int, object]:
    import torch

    by_category: dict[int, list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        by_category[entry["category_id"]].append(index)

    prototypes = {}
    for category_id, indices in by_category.items():
        prototype = embeddings[indices].mean(dim=0, keepdim=True)
        prototype = torch.nn.functional.normalize(prototype, dim=1).squeeze(0).cpu()
        prototypes[int(category_id)] = prototype
    return prototypes


def normalize_mean(embeddings):
    import torch

    prototype = embeddings.mean(dim=0, keepdim=True)
    return torch.nn.functional.normalize(prototype, dim=1).squeeze(0).cpu()




def select_prototype(
    category_id: int,
    reference_prototypes: dict[int, object],
    train_prototypes: dict[int, object],
    reference_weight: float,
    train_weight: float,
) -> tuple[object | None, str]:
    import torch

    reference_prototype = reference_prototypes.get(category_id)
    train_prototype = train_prototypes.get(category_id)
    if reference_prototype is not None and train_prototype is not None:
        blended = (reference_weight * reference_prototype) + (train_weight * train_prototype)
        blended = torch.nn.functional.normalize(blended.unsqueeze(0), dim=1).squeeze(0)
        return blended.cpu(), "reference+train"
    if reference_prototype is not None:
        return reference_prototype.cpu(), "reference"
    if train_prototype is not None:
        return train_prototype.cpu(), "train"
    return None, "missing"


if __name__ == "__main__":
    main()
