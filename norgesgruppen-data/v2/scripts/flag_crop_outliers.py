from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ngd_utils import load_json, save_json
from train_crop_classifier import replace_classifier


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Flag noisy crop labels using within-category and reference-image embedding similarity."
    )
    parser.add_argument("manifest", type=Path, help="Crop manifest JSON produced by extract_product_crops.py")
    parser.add_argument("checkpoint", type=Path, help="Crop-classifier checkpoint used as the embedding backbone")
    parser.add_argument(
        "--reference-root",
        type=Path,
        help="Optional ImageFolder-style root with clean reference images arranged by category_id.",
    )
    parser.add_argument(
        "--filtered-root",
        type=Path,
        default=Path("data/crops/train_by_category_filtered"),
        help="Output ImageFolder-style root with flagged crops removed.",
    )
    parser.add_argument(
        "--filtered-manifest",
        type=Path,
        default=Path("data/crops/train_crop_manifest_filtered.json"),
        help="Where to write the kept-manifest JSON.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/train_crop_outliers.json"),
        help="Where to write the outlier report JSON.",
    )
    parser.add_argument(
        "--suspect-manifest",
        type=Path,
        default=Path("data/crops/train_crop_manifest_suspect.json"),
        help="Where to write the manifest JSON for flagged crops that should be reviewed or down-weighted.",
    )
    parser.add_argument(
        "--hard-delete-manifest",
        type=Path,
        default=Path("data/crops/train_crop_manifest_hard_delete.json"),
        help="Where to write the manifest JSON for flagged crops that should be removed outright.",
    )
    parser.add_argument("--input-size", type=int, default=224, help="Validation crop size for embedding extraction.")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default="cuda", help="Torch device string.")
    parser.add_argument("--neighbor-k", type=int, default=5, help="Number of same-class neighbors for local similarity.")
    parser.add_argument("--min-class-size", type=int, default=8, help="Skip filtering classes smaller than this.")
    parser.add_argument(
        "--z-threshold",
        type=float,
        default=3.5,
        help="Robust z-score threshold above which a crop is flagged as an outlier.",
    )
    parser.add_argument(
        "--reference-z-threshold",
        type=float,
        default=3.0,
        help="Robust z-score threshold for low own-category reference similarity or weak reference margins.",
    )
    parser.add_argument(
        "--cross-category-margin",
        type=float,
        default=0.05,
        help="Minimum cosine-similarity margin by which another reference category must beat the assigned one.",
    )
    parser.add_argument(
        "--cross-category-min-similarity",
        type=float,
        default=0.70,
        help="Minimum competing-reference similarity before a cross-category mismatch is trusted.",
    )
    parser.add_argument(
        "--max-remove-fraction",
        type=float,
        default=0.05,
        help="Maximum fraction of crops removed per category.",
    )
    parser.add_argument(
        "--min-keep-per-class",
        type=int,
        default=1,
        help="Minimum number of crops to retain per category after filtering.",
    )
    parser.add_argument(
        "--hard-delete-z-threshold",
        type=float,
        default=5.0,
        help="Escalate flagged crops to hard-delete when anomaly_score exceeds this threshold and multiple reasons agree.",
    )
    parser.add_argument(
        "--keep-suspect",
        action="store_true",
        help="Keep suspect crops in the filtered dataset and only remove hard-delete entries.",
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
    checkpoint_path = args.checkpoint.resolve()
    filtered_root = args.filtered_root.resolve()
    filtered_manifest_path = args.filtered_manifest.resolve()
    report_path = args.report.resolve()
    suspect_manifest_path = args.suspect_manifest.resolve()
    hard_delete_manifest_path = args.hard_delete_manifest.resolve()

    manifest = load_json(manifest_path)
    if not isinstance(manifest, list):
        raise SystemExit(f"Manifest must be a JSON array: {manifest_path}")
    entries = [normalize_entry(entry) for entry in manifest]
    entries = [entry for entry in entries if entry["crop_path"].is_file()]
    if not entries:
        raise SystemExit(f"No usable crop files found in {manifest_path}")

    model, feature_extractor, class_names = load_embedding_model(
        checkpoint_path=checkpoint_path,
        device_name=args.device,
    )
    transform = build_eval_transform(args.input_size)
    embeddings = extract_embeddings(
        model=model,
        feature_extractor=feature_extractor,
        entries=entries,
        transform=transform,
        batch_size=args.batch_size,
        workers=args.workers,
    )
    reference_entries = load_reference_entries(args.reference_root.resolve()) if args.reference_root else []
    reference_prototypes = None
    if reference_entries:
        reference_embeddings = extract_embeddings(
            model=model,
            feature_extractor=feature_extractor,
            entries=reference_entries,
            transform=transform,
            batch_size=args.batch_size,
            workers=args.workers,
        )
        reference_prototypes = build_reference_prototypes(reference_entries, reference_embeddings)
    flagged_annotation_ids, category_summaries = flag_outliers(
        entries=entries,
        embeddings=embeddings,
        neighbor_k=args.neighbor_k,
        min_class_size=args.min_class_size,
        z_threshold=args.z_threshold,
        reference_z_threshold=args.reference_z_threshold,
        cross_category_margin=args.cross_category_margin,
        cross_category_min_similarity=args.cross_category_min_similarity,
        max_remove_fraction=args.max_remove_fraction,
        min_keep_per_class=args.min_keep_per_class,
        reference_prototypes=reference_prototypes,
    )

    flagged_entries = [entry for entry in entries if entry["annotation_id"] in flagged_annotation_ids]
    for entry in flagged_entries:
        entry["quality_decision"] = classify_quality_decision(
            entry=entry,
            hard_delete_z_threshold=args.hard_delete_z_threshold,
        )
    hard_delete_entries = [entry for entry in flagged_entries if entry["quality_decision"] == "hard_delete"]
    suspect_entries = [entry for entry in flagged_entries if entry["quality_decision"] == "suspect"]
    if args.keep_suspect:
        removed_annotation_ids = {int(entry["annotation_id"]) for entry in hard_delete_entries}
    else:
        removed_annotation_ids = {int(entry["annotation_id"]) for entry in flagged_entries}
    kept_entries = [entry for entry in entries if entry["annotation_id"] not in removed_annotation_ids]
    filtered_root = materialize_filtered_root(
        kept_entries=kept_entries,
        filtered_root=filtered_root,
        copy_files=args.copy_files,
    )

    save_json(filtered_manifest_path, [entry["manifest_entry"] for entry in kept_entries])
    save_json(suspect_manifest_path, [entry["manifest_entry"] for entry in suspect_entries])
    save_json(hard_delete_manifest_path, [entry["manifest_entry"] for entry in hard_delete_entries])
    report = {
        "manifest": str(manifest_path),
        "checkpoint": str(checkpoint_path),
        "class_names": class_names,
        "settings": {
            "input_size": args.input_size,
            "batch_size": args.batch_size,
            "neighbor_k": args.neighbor_k,
            "min_class_size": args.min_class_size,
            "z_threshold": args.z_threshold,
            "reference_z_threshold": args.reference_z_threshold,
            "cross_category_margin": args.cross_category_margin,
            "cross_category_min_similarity": args.cross_category_min_similarity,
            "max_remove_fraction": args.max_remove_fraction,
            "min_keep_per_class": args.min_keep_per_class,
            "hard_delete_z_threshold": args.hard_delete_z_threshold,
            "keep_suspect": bool(args.keep_suspect),
            "reference_root": str(args.reference_root.resolve()) if args.reference_root else None,
        },
        "summary": {
            "input_crop_count": len(entries),
            "kept_crop_count": len(kept_entries),
            "flagged_crop_count": len(flagged_entries),
            "flagged_fraction": round(len(flagged_entries) / max(1, len(entries)), 6),
            "removed_crop_count": len(removed_annotation_ids),
            "removed_fraction": round(len(removed_annotation_ids) / max(1, len(entries)), 6),
            "hard_delete_count": len(hard_delete_entries),
            "suspect_count": len(suspect_entries),
            "category_count": len(category_summaries),
            "reference_category_count": len(reference_prototypes["category_ids"]) if reference_prototypes else 0,
            "reference_image_count": len(reference_entries),
            "filtered_root": str(filtered_root),
            "filtered_manifest": str(filtered_manifest_path),
            "suspect_manifest": str(suspect_manifest_path),
            "hard_delete_manifest": str(hard_delete_manifest_path),
        },
        "categories": category_summaries,
        "flagged": [
            {
                "annotation_id": entry["annotation_id"],
                "category_id": entry["category_id"],
                "crop_file": entry["crop_path"].as_posix(),
                "image_id": entry["image_id"],
                "source_file": entry["source_file"],
                "combined_similarity": round(float(entry["combined_similarity"]), 6),
                "centroid_similarity": round(float(entry["centroid_similarity"]), 6),
                "neighbor_similarity": round(float(entry["neighbor_similarity"]), 6),
                "robust_z": round(float(entry["robust_z"]), 6),
                "reference_similarity": round_optional(entry.get("reference_similarity")),
                "competing_reference_similarity": round_optional(entry.get("competing_reference_similarity")),
                "competing_reference_category_id": entry.get("competing_reference_category_id"),
                "reference_margin": round_optional(entry.get("reference_margin")),
                "combined_robust_z": round_optional(entry.get("combined_robust_z")),
                "reference_robust_z": round_optional(entry.get("reference_robust_z")),
                "reference_margin_robust_z": round_optional(entry.get("reference_margin_robust_z")),
                "anomaly_score": round_optional(entry.get("anomaly_score")),
                "hard_reference_mismatch": bool(entry.get("hard_reference_mismatch")),
                "quality_decision": str(entry.get("quality_decision", "suspect")),
                "flag_reasons": list(entry.get("flag_reasons", [])),
            }
            for entry in sorted(flagged_entries, key=lambda item: float(item["robust_z"]), reverse=True)
        ],
    }
    save_json(report_path, report)

    print(f"report={report_path}")
    print(f"filtered_root={filtered_root}")
    print(f"filtered_manifest={filtered_manifest_path}")
    print(f"input_crops={len(entries)}")
    print(f"flagged_crops={len(flagged_entries)}")
    print(f"hard_delete_crops={len(hard_delete_entries)}")
    print(f"suspect_crops={len(suspect_entries)}")
    print(f"kept_crops={len(kept_entries)}")


def normalize_entry(entry: dict) -> dict:
    crop_path = Path(str(entry["crop_file"])).resolve()
    return {
        "manifest_entry": dict(entry),
        "annotation_id": int(entry["annotation_id"]),
        "category_id": int(entry["category_id"]),
        "image_id": int(entry["image_id"]),
        "source_file": str(entry.get("source_file", "")),
        "crop_path": crop_path,
    }


def load_reference_entries(reference_root: Path) -> list[dict]:
    if not reference_root.is_dir():
        raise SystemExit(f"Reference root does not exist or is not a directory: {reference_root}")

    entries: list[dict] = []
    next_annotation_id = -1
    for class_dir in sorted(reference_root.iterdir()):
        if not class_dir.is_dir():
            continue
        try:
            category_id = int(class_dir.name)
        except ValueError:
            continue
        for image_path in sorted(class_dir.iterdir()):
            if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            entries.append(
                {
                    "manifest_entry": {
                        "annotation_id": next_annotation_id,
                        "category_id": category_id,
                        "crop_file": image_path.as_posix(),
                        "image_id": -1,
                        "source_file": image_path.as_posix(),
                    },
                    "annotation_id": next_annotation_id,
                    "category_id": category_id,
                    "image_id": -1,
                    "source_file": image_path.as_posix(),
                    "crop_path": image_path.resolve(),
                }
            )
            next_annotation_id -= 1
    return entries


def load_embedding_model(checkpoint_path: Path, device_name: str):
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    arch = str(payload["arch"])
    class_names = [str(name) for name in payload["class_names"]]

    model = build_checkpoint_model(arch)
    replace_classifier(model, arch, len(class_names))
    model.load_state_dict(payload["model_state_dict"])

    device = torch.device(device_name if device_name else ("cuda" if torch.cuda.is_available() else "cpu"))
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA requested but torch.cuda.is_available() is False.")
    model.to(device)
    model.eval()

    if arch.startswith("resnet"):
        feature_extractor = ResNetFeatureExtractor(model)
    elif arch.startswith("convnext"):
        feature_extractor = ConvNeXtFeatureExtractor(model)
    else:
        raise SystemExit(f"Unsupported checkpoint architecture: {arch}")
    return model, feature_extractor, class_names


def build_checkpoint_model(arch: str):
    from torchvision.models import convnext_small, convnext_tiny, resnet18, resnet50

    if arch == "resnet18":
        return resnet18(weights=None)
    if arch == "resnet50":
        return resnet50(weights=None)
    if arch == "convnext_tiny":
        return convnext_tiny(weights=None)
    if arch == "convnext_small":
        return convnext_small(weights=None)
    raise SystemExit(f"Unsupported checkpoint architecture: {arch}")


def build_eval_transform(input_size: int):
    from torchvision import transforms

    normalize = transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225))
    return transforms.Compose(
        [
            transforms.Resize(int(round(input_size * 1.15))),
            transforms.CenterCrop(input_size),
            transforms.ToTensor(),
            normalize,
        ]
    )


class CropDataset(Dataset):
    def __init__(self, entries: list[dict], transform):
        self.entries = entries
        self.transform = transform

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, index: int):
        from PIL import Image

        image = Image.open(self.entries[index]["crop_path"]).convert("RGB")
        return self.transform(image), index


class ResNetFeatureExtractor:
    def __init__(self, model):
        self.backbone = torch.nn.Sequential(*(list(model.children())[:-1]))

    def __call__(self, images: torch.Tensor) -> torch.Tensor:
        return self.backbone(images).flatten(1)


class ConvNeXtFeatureExtractor:
    def __init__(self, model):
        self.model = model

    def __call__(self, images: torch.Tensor) -> torch.Tensor:
        x = self.model.features(images)
        x = self.model.avgpool(x)
        x = self.model.classifier[0](x)
        x = self.model.classifier[1](x)
        return x


def extract_embeddings(
    model,
    feature_extractor,
    entries: list[dict],
    transform,
    batch_size: int,
    workers: int,
) -> torch.Tensor:
    device = next(model.parameters()).device
    dataset = CropDataset(entries, transform)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=workers,
        pin_memory=device.type == "cuda",
    )
    outputs: list[torch.Tensor | None] = [None] * len(entries)

    with torch.no_grad():
        for images, indices in loader:
            images = images.to(device, non_blocking=True)
            features = feature_extractor(images)
            features = torch.nn.functional.normalize(features, dim=1).float().cpu()
            for row, index in enumerate(indices.tolist()):
                outputs[index] = features[row]

    return torch.stack([output for output in outputs if output is not None])


def build_reference_prototypes(reference_entries: list[dict], reference_embeddings: torch.Tensor) -> dict:
    by_category: dict[int, list[int]] = defaultdict(list)
    for index, entry in enumerate(reference_entries):
        by_category[entry["category_id"]].append(index)

    category_ids = sorted(by_category)
    prototype_rows: list[torch.Tensor] = []
    image_count_by_category: dict[int, int] = {}
    for category_id in category_ids:
        indices = by_category[category_id]
        prototype = reference_embeddings[indices].mean(dim=0, keepdim=True)
        prototype = torch.nn.functional.normalize(prototype, dim=1).squeeze(0)
        prototype_rows.append(prototype)
        image_count_by_category[category_id] = len(indices)

    return {
        "category_ids": category_ids,
        "embeddings": torch.stack(prototype_rows),
        "index_by_category": {category_id: index for index, category_id in enumerate(category_ids)},
        "image_count_by_category": image_count_by_category,
    }


def flag_outliers(
    entries: list[dict],
    embeddings: torch.Tensor,
    neighbor_k: int,
    min_class_size: int,
    z_threshold: float,
    reference_z_threshold: float,
    cross_category_margin: float,
    cross_category_min_similarity: float,
    max_remove_fraction: float,
    min_keep_per_class: int,
    reference_prototypes: dict | None,
) -> tuple[set[int], list[dict]]:
    by_category: dict[int, list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        by_category[entry["category_id"]].append(index)

    flagged_annotation_ids: set[int] = set()
    category_summaries: list[dict] = []
    reference_category_ids = list(reference_prototypes["category_ids"]) if reference_prototypes else []
    reference_embeddings = reference_prototypes["embeddings"] if reference_prototypes else None
    reference_index_by_category = (
        dict(reference_prototypes["index_by_category"])
        if reference_prototypes
        else {}
    )

    for category_id in sorted(by_category):
        indices = by_category[category_id]
        class_size = len(indices)
        category_embeddings = embeddings[indices]
        centroid = torch.nn.functional.normalize(category_embeddings.mean(dim=0, keepdim=True), dim=1)
        centroid_similarity = (category_embeddings @ centroid.T).squeeze(1)

        if class_size > 1:
            similarity_matrix = category_embeddings @ category_embeddings.T
            similarity_matrix.fill_diagonal_(-1.0)
            top_k = min(neighbor_k, class_size - 1)
            neighbor_similarity = similarity_matrix.topk(k=top_k, dim=1).values.mean(dim=1)
        else:
            neighbor_similarity = torch.ones(class_size, dtype=torch.float32)

        combined_similarity = (centroid_similarity + neighbor_similarity) / 2.0
        combined_robust_z = robust_low_zscore(combined_similarity)
        robust_z = combined_robust_z
        reference_similarity = torch.full((class_size,), float("nan"), dtype=torch.float32)
        competing_reference_similarity = torch.full((class_size,), float("nan"), dtype=torch.float32)
        reference_margin = torch.full((class_size,), float("nan"), dtype=torch.float32)
        reference_robust_z = torch.zeros(class_size, dtype=torch.float32)
        reference_margin_robust_z = torch.zeros(class_size, dtype=torch.float32)
        competing_reference_category_ids: list[int | None] = [None] * class_size
        has_own_reference = False

        if reference_embeddings is not None:
            reference_scores = category_embeddings @ reference_embeddings.T
            if category_id in reference_index_by_category:
                has_own_reference = True
                own_reference_index = reference_index_by_category[category_id]
                reference_similarity = reference_scores[:, own_reference_index]
                masked_scores = reference_scores.clone()
                masked_scores[:, own_reference_index] = -2.0
                competing_reference_similarity, competing_reference_indices = masked_scores.max(dim=1)
                competing_reference_category_ids = [
                    reference_category_ids[int(index)]
                    for index in competing_reference_indices.tolist()
                ]
                reference_margin = reference_similarity - competing_reference_similarity
                reference_robust_z = robust_low_zscore(reference_similarity)
                reference_margin_robust_z = robust_low_zscore(reference_margin)
            else:
                best_reference_similarity, best_reference_indices = reference_scores.max(dim=1)
                competing_reference_similarity = best_reference_similarity
                competing_reference_category_ids = [
                    reference_category_ids[int(index)]
                    for index in best_reference_indices.tolist()
                ]

        for offset, entry_index in enumerate(indices):
            entries[entry_index]["centroid_similarity"] = float(centroid_similarity[offset].item())
            entries[entry_index]["neighbor_similarity"] = float(neighbor_similarity[offset].item())
            entries[entry_index]["combined_similarity"] = float(combined_similarity[offset].item())
            entries[entry_index]["robust_z"] = float(robust_z[offset].item())
            entries[entry_index]["combined_robust_z"] = float(combined_robust_z[offset].item())
            entries[entry_index]["reference_similarity"] = (
                float(reference_similarity[offset].item())
                if has_own_reference
                else None
            )
            entries[entry_index]["competing_reference_similarity"] = (
                float(competing_reference_similarity[offset].item())
                if not torch.isnan(competing_reference_similarity[offset])
                else None
            )
            entries[entry_index]["competing_reference_category_id"] = competing_reference_category_ids[offset]
            entries[entry_index]["reference_margin"] = (
                float(reference_margin[offset].item())
                if has_own_reference
                else None
            )
            entries[entry_index]["reference_robust_z"] = (
                float(reference_robust_z[offset].item())
                if has_own_reference
                else None
            )
            entries[entry_index]["reference_margin_robust_z"] = (
                float(reference_margin_robust_z[offset].item())
                if has_own_reference
                else None
            )
            entries[entry_index]["flag_reasons"] = []
            entries[entry_index]["hard_reference_mismatch"] = False
            entries[entry_index]["anomaly_score"] = float(combined_robust_z[offset].item())

        hard_candidate_indices: list[int] = []
        soft_candidate_indices: list[int] = []
        for offset, entry_index in enumerate(indices):
            reasons: list[str] = []
            anomaly_score = float(combined_robust_z[offset].item())

            if class_size >= min_class_size and anomaly_score >= z_threshold:
                reasons.append("within_category_outlier")

            if has_own_reference:
                reference_score = float(reference_robust_z[offset].item())
                margin_score = float(reference_margin_robust_z[offset].item())
                anomaly_score = max(anomaly_score, reference_score, margin_score)
                if class_size >= min_class_size and reference_score >= reference_z_threshold:
                    reasons.append("low_reference_similarity")
                if class_size >= min_class_size and margin_score >= reference_z_threshold:
                    reasons.append("weak_reference_margin")
                competing_similarity = float(competing_reference_similarity[offset].item())
                margin_value = float(reference_margin[offset].item())
                if (
                    competing_reference_category_ids[offset] is not None
                    and competing_similarity >= cross_category_min_similarity
                    and margin_value <= -cross_category_margin
                ):
                    reasons.append("cross_category_reference_mismatch")

            entries[entry_index]["flag_reasons"] = reasons
            entries[entry_index]["hard_reference_mismatch"] = "cross_category_reference_mismatch" in reasons
            entries[entry_index]["anomaly_score"] = anomaly_score
            if not reasons:
                continue
            if "cross_category_reference_mismatch" in reasons:
                hard_candidate_indices.append(entry_index)
            else:
                soft_candidate_indices.append(entry_index)

        hard_candidate_indices = sorted(
            set(hard_candidate_indices),
            key=lambda entry_index: float(entries[entry_index]["anomaly_score"]),
            reverse=True,
        )
        soft_candidate_indices = sorted(
            set(soft_candidate_indices),
            key=lambda entry_index: float(entries[entry_index]["anomaly_score"]),
            reverse=True,
        )
        removal_cap = int(class_size * max_remove_fraction)
        if max_remove_fraction > 0 and removal_cap <= 0 and (hard_candidate_indices or soft_candidate_indices):
            removal_cap = 1
        max_allowed_removals = max(0, class_size - max(0, int(min_keep_per_class)))
        if removal_cap > max_allowed_removals:
            removal_cap = max_allowed_removals
        if removal_cap > 0:
            hard_keep = hard_candidate_indices[:removal_cap]
            remaining_budget = max(0, removal_cap - len(hard_keep))
            candidate_indices = hard_keep + soft_candidate_indices[:remaining_budget]
        else:
            candidate_indices = []

        for entry_index in candidate_indices:
            flagged_annotation_ids.add(int(entries[entry_index]["annotation_id"]))

        flagged_reason_counts = Counter(
            reason
            for entry_index in candidate_indices
            for reason in entries[entry_index]["flag_reasons"]
        )
        flagged_examples = [
            {
                "annotation_id": int(entries[entry_index]["annotation_id"]),
                "crop_file": entries[entry_index]["crop_path"].as_posix(),
                "combined_similarity": round(float(entries[entry_index]["combined_similarity"]), 6),
                "reference_similarity": round_optional(entries[entry_index].get("reference_similarity")),
                "competing_reference_similarity": round_optional(entries[entry_index].get("competing_reference_similarity")),
                "reference_margin": round_optional(entries[entry_index].get("reference_margin")),
                "anomaly_score": round(float(entries[entry_index]["anomaly_score"]), 6),
                "robust_z": round(float(entries[entry_index]["robust_z"]), 6),
                "flag_reasons": list(entries[entry_index]["flag_reasons"]),
            }
            for entry_index in candidate_indices[:10]
        ]
        category_summaries.append(
            {
                "category_id": category_id,
                "crop_count": class_size,
                "flagged_count": len(candidate_indices),
                "hard_mismatch_count": len(hard_candidate_indices),
                "median_similarity": round(float(combined_similarity.median().item()), 6),
                "min_similarity": round(float(combined_similarity.min().item()), 6),
                "max_similarity": round(float(combined_similarity.max().item()), 6),
                "median_robust_z": round(float(robust_z.median().item()), 6),
                "max_robust_z": round(float(robust_z.max().item()), 6),
                "median_reference_similarity": round_optional(
                    float(reference_similarity.median().item()) if has_own_reference else None
                ),
                "min_reference_similarity": round_optional(
                    float(reference_similarity.min().item()) if has_own_reference else None
                ),
                "median_reference_margin": round_optional(
                    float(reference_margin.median().item()) if has_own_reference else None
                ),
                "min_reference_margin": round_optional(
                    float(reference_margin.min().item()) if has_own_reference else None
                ),
                "flagged_reason_counts": dict(flagged_reason_counts),
                "flagged_examples": flagged_examples,
            }
        )

    return flagged_annotation_ids, category_summaries


def robust_low_zscore(values: torch.Tensor) -> torch.Tensor:
    median = values.median()
    deviation = (values - median).abs()
    mad = deviation.median().clamp_min(1e-6)
    scale = mad * 1.4826
    return (median - values) / scale


def round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def classify_quality_decision(entry: dict, hard_delete_z_threshold: float) -> str:
    reasons = set(entry.get("flag_reasons", []))
    anomaly_score = float(entry.get("anomaly_score", 0.0) or 0.0)
    if bool(entry.get("hard_reference_mismatch")):
        return "hard_delete"
    if "cross_category_reference_mismatch" in reasons:
        return "hard_delete"
    if "within_category_outlier" in reasons and anomaly_score >= hard_delete_z_threshold:
        if "low_reference_similarity" in reasons or "weak_reference_margin" in reasons:
            return "hard_delete"
    return "suspect"


def materialize_filtered_root(
    kept_entries: list[dict],
    filtered_root: Path,
    copy_files: bool,
) -> Path:
    if filtered_root.exists():
        try:
            shutil.rmtree(filtered_root)
        except OSError:
            filtered_root = next_available_root(filtered_root)
    filtered_root.mkdir(parents=True, exist_ok=True)

    for entry in kept_entries:
        source_path = entry["crop_path"]
        if source_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        destination = filtered_root / str(entry["category_id"]) / source_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        link_or_copy(source_path, destination, copy_files=copy_files)
    return filtered_root


def next_available_root(filtered_root: Path) -> Path:
    base_name = filtered_root.name
    parent = filtered_root.parent
    for suffix in range(2, 1000):
        candidate = parent / f"{base_name}_{suffix}"
        if not candidate.exists():
            return candidate
    raise SystemExit(f"Unable to find a free fallback output directory near {filtered_root}")


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
