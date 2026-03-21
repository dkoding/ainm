from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


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

    class_names = sorted(path.name for path in train_dir.iterdir() if path.is_dir())
    train_dataset = CropFolderDataset(
        [train_dir, *extra_train_dirs],
        class_names,
        train_transform,
        ignore_unknown=True,
    )
    val_dataset = CropFolderDataset(val_dir, class_names, val_transform, ignore_unknown=True)

    num_classes = len(train_dataset.class_names)
    if num_classes <= 0:
        raise SystemExit("No classes found in crop dataset.")

    replace_classifier(model, args.arch, num_classes)

    device = torch.device(args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu"))
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA requested but torch.cuda.is_available() is False.")
    model.to(device)

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
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

    class_counts = count_classes(train_dataset.targets, num_classes)
    class_weights = build_class_weights(class_counts).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights, label_smoothing=args.label_smoothing)
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
            criterion=criterion,
            optimizer=optimizer,
            scaler=scaler,
            device=device,
            training=True,
        )
        if device.type == "cuda":
            torch.cuda.empty_cache()
        val_loss, val_top1 = run_epoch(
            model=model,
            loader=val_loader,
            criterion=criterion,
            optimizer=None,
            scaler=None,
            device=device,
            training=False,
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


def build_class_weights(class_counts: torch.Tensor) -> torch.Tensor:
    weights = torch.zeros_like(class_counts)
    positive = class_counts > 0
    weights[positive] = 1.0 / torch.sqrt(class_counts[positive])
    weights = weights / weights.mean().clamp_min(1e-8)
    return weights


class CropFolderDataset(Dataset):
    def __init__(self, roots: Path | list[Path], class_names: list[str], transform, ignore_unknown: bool):
        if isinstance(roots, Path):
            self.roots = [roots]
        else:
            self.roots = [Path(root) for root in roots]
        self.class_names = list(class_names)
        self.class_to_idx = {name: index for index, name in enumerate(self.class_names)}
        self.transform = transform
        self.samples: list[tuple[Path, int]] = []
        self.targets: list[int] = []

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
                    self.samples.append((image_path, target))
                    self.targets.append(target)

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
        return image, target


def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer,
    scaler,
    device: torch.device,
    training: bool,
) -> tuple[float, float]:
    model.train(training)
    total_loss = 0.0
    total_examples = 0
    total_correct = 0

    for images, targets in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)

        if training:
            optimizer.zero_grad(set_to_none=True)

        with torch.amp.autocast(device_type=device.type, enabled=device.type == "cuda"):
            logits = model(images)
            loss = criterion(logits, targets)

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
