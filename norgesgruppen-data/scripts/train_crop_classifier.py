from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a crop classifier from ImageFolder-style directories.")
    parser.add_argument("train_dir", type=Path, help="ImageFolder directory with training crops.")
    parser.add_argument("val_dir", type=Path, help="ImageFolder directory with validation crops.")
    parser.add_argument(
        "--extra-train-dir",
        action="append",
        type=Path,
        default=[],
        help="Optional extra ImageFolder directory to merge into the training set.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/crop_classifier"),
        help="Directory for checkpoints and history.",
    )
    parser.add_argument(
        "--init-checkpoint",
        type=Path,
        help="Optional checkpoint to warm-start from. Matching backbone weights are restored, and matching classifier rows are copied by class name.",
    )
    parser.add_argument("--arch", choices=("resnet18", "resnet50", "convnext_tiny", "convnext_small"), default="resnet50")
    parser.add_argument("--epochs", type=int, default=30, help="Maximum epoch count before early stopping.")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument(
        "--val-batch-size",
        type=int,
        help="Optional validation batch size. Defaults to --batch-size when omitted.",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--val-workers",
        type=int,
        default=0,
        help="Validation DataLoader workers. Keep low on Windows to avoid doubling worker memory during eval.",
    )
    parser.add_argument(
        "--prefetch-factor",
        type=int,
        default=1,
        help="DataLoader prefetch factor when workers > 0. Lower this on Windows if shared-memory mappings fail.",
    )
    parser.add_argument(
        "--persistent-workers",
        action="store_true",
        help="Keep DataLoader workers alive across epochs when workers > 0.",
    )
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--min-lr", type=float, default=1e-5)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--label-smoothing", type=float, default=0.1)
    parser.add_argument(
        "--sampler",
        choices=("shuffle", "class_balanced"),
        default="shuffle",
        help="Training sampler. class_balanced uses weighted sampling to surface rare classes more often.",
    )
    parser.add_argument(
        "--sampler-power",
        type=float,
        default=0.75,
        help="Exponent used for class-balanced sampling weights: weight = count^-power.",
    )
    parser.add_argument(
        "--suspect-manifest",
        action="append",
        type=Path,
        default=[],
        help="Optional manifest of suspect crops to down-weight during training. Repeatable.",
    )
    parser.add_argument(
        "--suspect-sample-weight",
        type=float,
        default=0.35,
        help="Per-sample loss/sampler weight for crops listed in --suspect-manifest.",
    )
    parser.add_argument(
        "--mixup-alpha",
        type=float,
        default=0.0,
        help="MixUp Beta distribution alpha. Set > 0 to enable MixUp.",
    )
    parser.add_argument(
        "--cutmix-alpha",
        type=float,
        default=0.0,
        help="CutMix Beta distribution alpha. Set > 0 to enable CutMix.",
    )
    parser.add_argument(
        "--mix-prob",
        type=float,
        default=0.0,
        help="Probability of applying MixUp or CutMix to a training batch.",
    )
    parser.add_argument(
        "--cutmix-prob",
        type=float,
        default=0.5,
        help="When batch mixing is enabled, probability of choosing CutMix instead of MixUp.",
    )
    parser.add_argument(
        "--embedding-loss-weight",
        type=float,
        default=0.0,
        help="Auxiliary supervised-contrastive loss weight for fine-grained embedding separation.",
    )
    parser.add_argument(
        "--embedding-loss-temperature",
        type=float,
        default=0.1,
        help="Temperature used by the auxiliary supervised-contrastive loss.",
    )
    parser.add_argument("--input-size", type=int, default=224)
    parser.add_argument("--scheduler", choices=("none", "cosine"), default="cosine")
    parser.add_argument("--patience", type=int, default=5, help="Stop after this many epochs without validation improvement.")
    parser.add_argument("--min-improvement", type=float, default=1e-4, help="Minimum validation gain to reset patience.")
    parser.add_argument("--device", default="cuda", help="Torch device string.")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    train_dir = args.train_dir.resolve()
    val_dir = args.val_dir.resolve()
    extra_train_dirs = [path.resolve() for path in args.extra_train_dir]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    from torchvision import transforms
    model = build_model(args.arch)

    normalize = transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225))
    train_transform = transforms.Compose(
        [
            transforms.RandomResizedCrop(args.input_size, scale=(0.65, 1.0)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.15, hue=0.03),
            transforms.ToTensor(),
            normalize,
            transforms.RandomErasing(p=0.1, scale=(0.02, 0.12)),
        ]
    )
    val_transform = transforms.Compose(
        [
            transforms.Resize(int(round(args.input_size * 1.15))),
            transforms.CenterCrop(args.input_size),
            transforms.ToTensor(),
            normalize,
        ]
    )

    class_names = collect_class_names([train_dir, *extra_train_dirs])
    suspect_paths = load_suspect_paths(args.suspect_manifest)
    suspect_sample_weight = max(0.0, float(args.suspect_sample_weight))
    train_dataset = CropFolderDataset(
        [train_dir, *extra_train_dirs],
        class_names,
        train_transform,
        ignore_unknown=True,
        sample_weight_by_path={path: suspect_sample_weight for path in suspect_paths},
    )
    val_dataset = CropFolderDataset(val_dir, class_names, val_transform, ignore_unknown=True)

    num_classes = len(train_dataset.class_names)
    if num_classes <= 0:
        raise SystemExit("No classes found in crop dataset.")

    replace_classifier(model, args.arch, num_classes)
    if args.init_checkpoint:
        load_initial_checkpoint(
            model=model,
            arch=args.arch,
            class_names=train_dataset.class_names,
            checkpoint_path=args.init_checkpoint.resolve(),
        )

    device = torch.device(args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu"))
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA requested but torch.cuda.is_available() is False.")
    model.to(device)

    class_counts = count_classes(train_dataset.targets, num_classes)
    train_sampling_weights = build_sampler_weights(
        targets=train_dataset.targets,
        class_counts=class_counts,
        sample_weights=train_dataset.sample_weights,
        power=args.sampler_power,
    )
    train_sampler = None
    train_shuffle = True
    if args.sampler == "class_balanced":
        train_sampler = WeightedRandomSampler(
            weights=train_sampling_weights.double(),
            num_samples=len(train_sampling_weights),
            replacement=True,
        )
        train_shuffle = False

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=train_shuffle,
        sampler=train_sampler,
        num_workers=args.workers,
        pin_memory=device.type == "cuda",
        persistent_workers=bool(args.persistent_workers and args.workers > 0),
        prefetch_factor=max(1, int(args.prefetch_factor)) if args.workers > 0 else None,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.val_batch_size or args.batch_size,
        shuffle=False,
        num_workers=args.val_workers,
        pin_memory=device.type == "cuda",
        persistent_workers=False,
        prefetch_factor=max(1, int(args.prefetch_factor)) if args.val_workers > 0 else None,
    )

    class_weights = build_class_weights(class_counts).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights, label_smoothing=args.label_smoothing, reduction="none")
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = build_scheduler(optimizer, args)
    scaler = torch.amp.GradScaler(device.type, enabled=device.type == "cuda")

    history: list[dict] = []
    best_top1 = -1.0
    best_epoch = 0
    epochs_without_improvement = 0
    best_path = output_dir / "best_crop_classifier.pt"
    last_path = output_dir / "last_crop_classifier.pt"
    history_path = output_dir / "history.json"
    status_path = output_dir / "status.json"
    metadata_path = output_dir / "run_metadata.json"

    write_json(
        metadata_path,
        {
            "started_at": utc_now_iso(),
            "pid": os.getpid(),
            "train_dir": str(train_dir),
            "val_dir": str(val_dir),
            "extra_train_dirs": [str(path) for path in extra_train_dirs],
            "device": str(device),
            "num_classes": num_classes,
            "train_samples": len(train_dataset),
            "val_samples": len(val_dataset),
            "args": serialize_json(vars(args)),
        },
    )

    for epoch in range(1, args.epochs + 1):
        train_loss, train_top1 = run_epoch(
            model=model,
            loader=train_loader,
            arch=args.arch,
            criterion=criterion,
            class_weights=class_weights,
            optimizer=optimizer,
            scaler=scaler,
            device=device,
            training=True,
            label_smoothing=args.label_smoothing,
            mixup_alpha=args.mixup_alpha,
            cutmix_alpha=args.cutmix_alpha,
            mix_prob=args.mix_prob,
            cutmix_prob=args.cutmix_prob,
            embedding_loss_weight=args.embedding_loss_weight,
            embedding_loss_temperature=args.embedding_loss_temperature,
        )
        if device.type == "cuda":
            torch.cuda.empty_cache()
        val_loss, val_top1 = run_epoch(
            model=model,
            loader=val_loader,
            arch=args.arch,
            criterion=criterion,
            class_weights=class_weights,
            optimizer=None,
            scaler=None,
            device=device,
            training=False,
            label_smoothing=args.label_smoothing,
            mixup_alpha=0.0,
            cutmix_alpha=0.0,
            mix_prob=0.0,
            cutmix_prob=0.0,
            embedding_loss_weight=0.0,
            embedding_loss_temperature=args.embedding_loss_temperature,
        )

        row = {
            "epoch": epoch,
            "train_loss": round(train_loss, 6),
            "train_top1": round(train_top1, 6),
            "val_loss": round(val_loss, 6),
            "val_top1": round(val_top1, 6),
        }
        history.append(row)
        print(
            f"epoch={epoch} "
            f"train_loss={row['train_loss']:.6f} train_top1={row['train_top1']:.6f} "
            f"val_loss={row['val_loss']:.6f} val_top1={row['val_top1']:.6f}",
            flush=True,
        )

        save_checkpoint(
            path=last_path,
            model=model,
            args=args,
            class_names=train_dataset.class_names,
            history=history,
        )
        if val_top1 > best_top1 + args.min_improvement:
            best_top1 = val_top1
            best_epoch = epoch
            epochs_without_improvement = 0
            save_checkpoint(
                path=best_path,
                model=model,
                args=args,
                class_names=train_dataset.class_names,
                history=history,
            )
        else:
            epochs_without_improvement += 1
        if scheduler is not None:
            scheduler.step()
        write_json(history_path, history)
        write_json(
            status_path,
            build_status_payload(
                history=history,
                best_epoch=best_epoch,
                best_top1=best_top1,
                epochs_without_improvement=epochs_without_improvement,
                stage="running",
            ),
        )
        if epochs_without_improvement >= args.patience:
            print(
                "early_stop="
                f"epoch={epoch} best_epoch={best_epoch} "
                f"best_top1={best_top1:.6f} patience={args.patience}",
                flush=True,
            )
            write_json(
                status_path,
                build_status_payload(
                    history=history,
                    best_epoch=best_epoch,
                    best_top1=best_top1,
                    epochs_without_improvement=epochs_without_improvement,
                    stage="early_stopped",
                ),
            )
            break

    write_json(history_path, history)
    write_json(
        status_path,
        build_status_payload(
            history=history,
            best_epoch=best_epoch,
            best_top1=best_top1,
            epochs_without_improvement=epochs_without_improvement,
            stage="completed" if epochs_without_improvement < args.patience else "early_stopped",
        ),
    )
    print(f"best_epoch={best_epoch}", flush=True)
    print(f"best_top1={best_top1:.6f}", flush=True)
    print(f"best_checkpoint={best_path}", flush=True)


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_json(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): serialize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_json(item) for item in value]
    return value


def write_json(path: Path, payload) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    serialized = json.dumps(payload, indent=2)
    last_error: PermissionError | None = None
    for attempt in range(8):
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            temp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))

    try:
        path.write_text(serialized, encoding="utf-8")
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        return
    except PermissionError:
        pass

    if last_error is not None:
        raise last_error
    raise PermissionError(f"Could not write JSON file: {path}")


def build_status_payload(
    history: list[dict],
    best_epoch: int,
    best_top1: float,
    epochs_without_improvement: int,
    stage: str,
) -> dict:
    return {
        "updated_at": utc_now_iso(),
        "stage": stage,
        "epoch_count": len(history),
        "current": history[-1] if history else None,
        "best_epoch": best_epoch,
        "best_top1": round(best_top1, 6) if best_top1 >= 0.0 else None,
        "best": max(history, key=lambda row: row["val_top1"]) if history else None,
        "epochs_without_improvement": epochs_without_improvement,
    }


def count_classes(targets: list[int], num_classes: int) -> torch.Tensor:
    counts = torch.zeros(num_classes, dtype=torch.float32)
    for target in targets:
        counts[int(target)] += 1
    return counts


def collect_class_names(roots: list[Path]) -> list[str]:
    class_names: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_dir():
                class_names.add(path.name)
    return sorted(class_names)


def load_suspect_paths(manifest_paths: list[Path]) -> set[Path]:
    suspect_paths: set[Path] = set()
    for manifest_path in manifest_paths:
        resolved_path = manifest_path.resolve()
        if not resolved_path.exists():
            raise SystemExit(f"Missing suspect manifest: {resolved_path}")
        loaded = json.loads(resolved_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise SystemExit(f"Suspect manifest must be a JSON array: {resolved_path}")
        for entry in loaded:
            crop_file = entry.get("crop_file")
            if crop_file is None:
                continue
            suspect_paths.add(Path(str(crop_file)).resolve())
    return suspect_paths


def build_class_weights(class_counts: torch.Tensor) -> torch.Tensor:
    weights = torch.zeros_like(class_counts)
    positive = class_counts > 0
    weights[positive] = 1.0 / torch.sqrt(class_counts[positive])
    weights = weights / weights.mean().clamp_min(1e-8)
    return weights


def build_sampler_weights(
    targets: list[int],
    class_counts: torch.Tensor,
    sample_weights: list[float],
    power: float,
) -> torch.Tensor:
    weights = torch.ones(len(targets), dtype=torch.float32)
    for index, target in enumerate(targets):
        class_count = float(class_counts[int(target)].item())
        class_weight = class_count ** (-float(power)) if class_count > 0.0 else 1.0
        weights[index] = float(sample_weights[index]) * float(class_weight)
    return weights.clamp_min(1e-8)


class CropFolderDataset(Dataset):
    def __init__(
        self,
        roots: Path | list[Path],
        class_names: list[str],
        transform,
        ignore_unknown: bool,
        sample_weight_by_path: dict[Path, float] | None = None,
    ):
        if isinstance(roots, Path):
            self.roots = [roots]
        else:
            self.roots = [Path(root) for root in roots]
        self.class_names = list(class_names)
        self.class_to_idx = {name: index for index, name in enumerate(self.class_names)}
        self.transform = transform
        self.samples: list[tuple[Path, int]] = []
        self.targets: list[int] = []
        self.sample_weights: list[float] = []
        self.sample_weight_by_path = sample_weight_by_path or {}

        for root in self.roots:
            for class_dir in sorted(root.iterdir()):
                if not class_dir.is_dir():
                    continue
                class_name = class_dir.name
                if class_name not in self.class_to_idx:
                    if ignore_unknown:
                        continue
                    raise SystemExit(f"Unexpected class directory in {root}: {class_name}")
                target = self.class_to_idx[class_name]
                for image_path in sorted(class_dir.iterdir()):
                    if not image_path.is_file() or image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                        continue
                    resolved_path = image_path.resolve()
                    self.samples.append((resolved_path, target))
                    self.targets.append(target)
                    self.sample_weights.append(float(self.sample_weight_by_path.get(resolved_path, 1.0)))

        if not self.samples:
            raise SystemExit(f"No crop images found in {', '.join(str(root) for root in self.roots)}")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        from PIL import Image

        image_path, target = self.samples[index]
        image = Image.open(image_path).convert("RGB")
        if self.transform is not None:
            image = self.transform(image)
        return image, target, float(self.sample_weights[index])


def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    arch: str,
    criterion: nn.Module,
    class_weights: torch.Tensor,
    optimizer,
    scaler,
    device: torch.device,
    training: bool,
    label_smoothing: float,
    mixup_alpha: float,
    cutmix_alpha: float,
    mix_prob: float,
    cutmix_prob: float,
    embedding_loss_weight: float,
    embedding_loss_temperature: float,
) -> tuple[float, float]:
    model.train(training)
    total_loss = 0.0
    total_examples = 0
    total_correct = 0

    for images, targets, sample_weights in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        sample_weights = sample_weights.to(device=device, dtype=torch.float32, non_blocking=True)
        mixed_targets = None

        if training:
            optimizer.zero_grad(set_to_none=True)
            images, mixed_targets = apply_batch_mixing(
                images=images,
                targets=targets,
                mix_prob=mix_prob,
                mixup_alpha=mixup_alpha,
                cutmix_alpha=cutmix_alpha,
                cutmix_prob=cutmix_prob,
                num_classes=int(class_weights.numel()),
                label_smoothing=label_smoothing,
            )

        with torch.amp.autocast(device_type=device.type, enabled=device.type == "cuda"):
            logits, features = forward_with_features(model=model, arch=arch, images=images)
            if mixed_targets is None:
                per_example_losses = criterion(logits, targets)
                weighted_losses = per_example_losses * sample_weights
                loss = weighted_losses.sum() / sample_weights.sum().clamp_min(1e-8)
            else:
                loss = soft_target_cross_entropy(
                    logits=logits,
                    targets=mixed_targets,
                    class_weights=class_weights,
                    sample_weights=sample_weights,
                )
            if training and mixed_targets is None and embedding_loss_weight > 0.0:
                contrastive_loss = supervised_contrastive_loss(
                    features=features,
                    targets=targets,
                    temperature=embedding_loss_temperature,
                )
                if contrastive_loss is not None:
                    loss = loss + (float(embedding_loss_weight) * contrastive_loss)

        if training:
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

        total_loss += float(loss.item()) * targets.size(0)
        total_examples += targets.size(0)
        total_correct += int((logits.argmax(dim=1) == targets).sum().item())

    if total_examples <= 0:
        return 0.0, 0.0
    return total_loss / total_examples, total_correct / total_examples


def forward_with_features(model: nn.Module, arch: str, images: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    if arch == "resnet18" or arch == "resnet50":
        x = model.conv1(images)
        x = model.bn1(x)
        x = model.relu(x)
        x = model.maxpool(x)
        x = model.layer1(x)
        x = model.layer2(x)
        x = model.layer3(x)
        x = model.layer4(x)
        x = model.avgpool(x)
        features = torch.flatten(x, 1)
        logits = model.fc(features)
        return logits, features
    if arch == "convnext_tiny" or arch == "convnext_small":
        x = model.features(images)
        x = model.avgpool(x)
        x = model.classifier[0](x)
        features = model.classifier[1](x)
        logits = model.classifier[2](features)
        return logits, features
    raise ValueError(f"Unsupported architecture: {arch}")


def apply_batch_mixing(
    images: torch.Tensor,
    targets: torch.Tensor,
    mix_prob: float,
    mixup_alpha: float,
    cutmix_alpha: float,
    cutmix_prob: float,
    num_classes: int,
    label_smoothing: float,
) -> tuple[torch.Tensor, torch.Tensor | None]:
    if images.size(0) < 2:
        return images, None
    if max(0.0, float(mix_prob)) <= 0.0:
        return images, None
    if torch.rand(1).item() >= float(mix_prob):
        return images, None

    use_cutmix = float(cutmix_alpha) > 0.0 and (
        float(mixup_alpha) <= 0.0 or torch.rand(1).item() < float(cutmix_prob)
    )
    alpha = float(cutmix_alpha if use_cutmix else mixup_alpha)
    if alpha <= 0.0:
        return images, None

    permutation = torch.randperm(images.size(0), device=images.device)
    lam = sample_beta(alpha, images.device)
    if use_cutmix:
        mixed_images, lam = apply_cutmix(images, permutation, lam)
    else:
        mixed_images = (lam * images) + ((1.0 - lam) * images[permutation])
    mixed_targets = build_mixed_targets(
        targets=targets,
        permutation=permutation,
        lam=lam,
        num_classes=num_classes,
        label_smoothing=label_smoothing,
    )
    return mixed_images, mixed_targets


def sample_beta(alpha: float, device: torch.device | str) -> float:
    distribution = torch.distributions.Beta(alpha, alpha)
    return float(distribution.sample().to(device).item())


def apply_cutmix(images: torch.Tensor, permutation: torch.Tensor, lam: float) -> tuple[torch.Tensor, float]:
    mixed = images.clone()
    _, _, height, width = mixed.shape
    cut_ratio = float((1.0 - lam) ** 0.5)
    cut_width = max(1, int(width * cut_ratio))
    cut_height = max(1, int(height * cut_ratio))
    center_x = int(torch.randint(0, width, (1,), device=mixed.device).item())
    center_y = int(torch.randint(0, height, (1,), device=mixed.device).item())

    x1 = max(0, center_x - (cut_width // 2))
    x2 = min(width, center_x + (cut_width // 2))
    y1 = max(0, center_y - (cut_height // 2))
    y2 = min(height, center_y + (cut_height // 2))
    if x2 <= x1 or y2 <= y1:
        return mixed, lam

    mixed[:, :, y1:y2, x1:x2] = mixed[permutation, :, y1:y2, x1:x2]
    box_area = float((x2 - x1) * (y2 - y1))
    lam_adjusted = 1.0 - (box_area / float(width * height))
    return mixed, lam_adjusted


def build_mixed_targets(
    targets: torch.Tensor,
    permutation: torch.Tensor,
    lam: float,
    num_classes: int,
    label_smoothing: float,
) -> torch.Tensor:
    one_hot = torch.nn.functional.one_hot(targets, num_classes=num_classes).to(dtype=torch.float32)
    permuted = one_hot[permutation]
    mixed = (lam * one_hot) + ((1.0 - lam) * permuted)
    if label_smoothing > 0.0:
        mixed = apply_soft_target_label_smoothing(mixed, label_smoothing)
    return mixed


def apply_soft_target_label_smoothing(targets: torch.Tensor, label_smoothing: float) -> torch.Tensor:
    if label_smoothing <= 0.0:
        return targets
    class_count = targets.size(1)
    return (targets * (1.0 - label_smoothing)) + (label_smoothing / float(class_count))


def soft_target_cross_entropy(
    logits: torch.Tensor,
    targets: torch.Tensor,
    class_weights: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    log_probabilities = torch.nn.functional.log_softmax(logits, dim=1)
    weighted_targets = targets * class_weights.unsqueeze(0)
    per_example_losses = -(weighted_targets * log_probabilities).sum(dim=1)
    per_example_losses = per_example_losses * sample_weights
    return per_example_losses.sum() / sample_weights.sum().clamp_min(1e-8)


def supervised_contrastive_loss(
    features: torch.Tensor,
    targets: torch.Tensor,
    temperature: float,
) -> torch.Tensor | None:
    normalized = torch.nn.functional.normalize(features.float(), dim=1)
    logits = normalized @ normalized.T
    logits = logits / max(1e-4, float(temperature))
    logits = logits - logits.max(dim=1, keepdim=True).values.detach()

    self_mask = torch.eye(logits.size(0), device=logits.device, dtype=torch.bool)
    positive_mask = targets.unsqueeze(0).eq(targets.unsqueeze(1)) & ~self_mask
    if not bool(positive_mask.any().item()):
        return None

    exp_logits = torch.exp(logits) * (~self_mask).to(dtype=logits.dtype)
    log_prob = logits - torch.log(exp_logits.sum(dim=1, keepdim=True).clamp_min(1e-8))
    positive_counts = positive_mask.sum(dim=1)
    valid = positive_counts > 0
    if not bool(valid.any().item()):
        return None
    mean_log_prob_positive = (log_prob * positive_mask.to(dtype=log_prob.dtype)).sum(dim=1)
    mean_log_prob_positive = mean_log_prob_positive / positive_counts.clamp_min(1).to(dtype=log_prob.dtype)
    return -mean_log_prob_positive[valid].mean()


def save_checkpoint(
    path: Path,
    model: nn.Module,
    args: argparse.Namespace,
    class_names: list[str],
    history: list[dict],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_state_dict": model.state_dict(),
        "arch": args.arch,
        "class_names": list(class_names),
        "train_dir": str(args.train_dir),
        "val_dir": str(args.val_dir),
        "history": list(history),
    }
    torch.save(payload, path)


def load_initial_checkpoint(model: nn.Module, arch: str, class_names: list[str], checkpoint_path: Path) -> None:
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    checkpoint_arch = str(payload.get("arch", ""))
    if checkpoint_arch != arch:
        raise SystemExit(
            f"Initial checkpoint architecture mismatch: expected {arch}, found {checkpoint_arch} in {checkpoint_path}"
        )

    checkpoint_state = payload.get("model_state_dict")
    if not isinstance(checkpoint_state, dict):
        raise SystemExit(f"Initial checkpoint is missing model_state_dict: {checkpoint_path}")

    model_state = model.state_dict()
    classifier_weight_key, classifier_bias_key = classifier_parameter_names(arch)
    filtered_state = {
        key: value
        for key, value in checkpoint_state.items()
        if key in model_state
        and model_state[key].shape == value.shape
        and key not in {classifier_weight_key, classifier_bias_key}
    }
    load_result = model.load_state_dict(filtered_state, strict=False)
    if load_result.unexpected_keys:
        raise SystemExit(f"Unexpected keys in initial checkpoint load: {load_result.unexpected_keys}")

    checkpoint_class_names = [str(name) for name in payload.get("class_names", [])]
    if not checkpoint_class_names:
        return

    current_weight = model_state[classifier_weight_key]
    current_bias = model_state[classifier_bias_key]
    restored_weight = current_weight.clone()
    restored_bias = current_bias.clone()
    checkpoint_weight = checkpoint_state.get(classifier_weight_key)
    checkpoint_bias = checkpoint_state.get(classifier_bias_key)
    if checkpoint_weight is None or checkpoint_bias is None:
        return

    old_index_by_name = {str(name): index for index, name in enumerate(checkpoint_class_names)}
    copied_rows = 0
    for new_index, class_name in enumerate(class_names):
        old_index = old_index_by_name.get(str(class_name))
        if old_index is None:
            continue
        restored_weight[new_index] = checkpoint_weight[old_index]
        restored_bias[new_index] = checkpoint_bias[old_index]
        copied_rows += 1

    with torch.no_grad():
        parameter_dict = dict(model.named_parameters())
        buffer_dict = dict(model.named_buffers())
        target_weight = parameter_dict.get(classifier_weight_key)
        target_bias = parameter_dict.get(classifier_bias_key)
        if target_weight is None:
            target_weight = buffer_dict.get(classifier_weight_key)
        if target_bias is None:
            target_bias = buffer_dict.get(classifier_bias_key)
        if target_weight is None or target_bias is None:
            raise SystemExit(f"Could not locate classifier parameters for {arch}")
        target_weight.copy_(restored_weight)
        target_bias.copy_(restored_bias)

    print(
        f"init_checkpoint={checkpoint_path} restored_backbone_keys={len(filtered_state)} copied_classifier_rows={copied_rows}",
        flush=True,
    )


def build_model(arch: str) -> nn.Module:
    from torchvision.models import (
        ConvNeXt_Small_Weights,
        ConvNeXt_Tiny_Weights,
        ResNet18_Weights,
        ResNet50_Weights,
        convnext_small,
        convnext_tiny,
        resnet18,
        resnet50,
    )

    if arch == "resnet18":
        return resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
    if arch == "resnet50":
        return resnet50(weights=ResNet50_Weights.IMAGENET1K_V2)
    if arch == "convnext_tiny":
        return convnext_tiny(weights=ConvNeXt_Tiny_Weights.IMAGENET1K_V1)
    if arch == "convnext_small":
        return convnext_small(weights=ConvNeXt_Small_Weights.IMAGENET1K_V1)
    raise ValueError(f"Unsupported architecture: {arch}")


def replace_classifier(model: nn.Module, arch: str, num_classes: int) -> None:
    if arch.startswith("resnet"):
        in_features = model.fc.in_features
        model.fc = nn.Linear(in_features, num_classes)
        return
    if arch in {"convnext_tiny", "convnext_small"}:
        in_features = model.classifier[2].in_features
        model.classifier[2] = nn.Linear(in_features, num_classes)
        return
    raise ValueError(f"Unsupported architecture: {arch}")


def classifier_parameter_names(arch: str) -> tuple[str, str]:
    if arch.startswith("resnet"):
        return "fc.weight", "fc.bias"
    if arch in {"convnext_tiny", "convnext_small"}:
        return "classifier.2.weight", "classifier.2.bias"
    raise ValueError(f"Unsupported architecture: {arch}")


def build_scheduler(optimizer, args: argparse.Namespace):
    if args.scheduler == "none":
        return None
    if args.scheduler == "cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=max(1, args.epochs),
            eta_min=args.min_lr,
        )
    raise ValueError(f"Unsupported scheduler: {args.scheduler}")


if __name__ == "__main__":
    main()
