from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a crop classifier from ImageFolder-style directories.")
    parser.add_argument("train_dir", type=Path, help="ImageFolder directory with training crops.")
    parser.add_argument("val_dir", type=Path, help="ImageFolder directory with validation crops.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/crop_classifier"),
        help="Directory for checkpoints and history.",
    )
    parser.add_argument("--arch", choices=("resnet18", "resnet50"), default="resnet50")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--label-smoothing", type=float, default=0.1)
    parser.add_argument("--device", default="cuda", help="Torch device string.")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    train_dir = args.train_dir.resolve()
    val_dir = args.val_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    from torchvision import transforms
    from torchvision.models import (
        ResNet18_Weights,
        ResNet50_Weights,
        resnet18,
        resnet50,
    )

    if args.arch == "resnet18":
        weights = ResNet18_Weights.IMAGENET1K_V1
        model = resnet18(weights=weights)
    else:
        weights = ResNet50_Weights.IMAGENET1K_V2
        model = resnet50(weights=weights)

    normalize = transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225))
    train_transform = transforms.Compose(
        [
            transforms.RandomResizedCrop(224, scale=(0.7, 1.0)),
            transforms.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.15, hue=0.03),
            transforms.ToTensor(),
            normalize,
        ]
    )
    val_transform = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            normalize,
        ]
    )

    class_names = sorted(path.name for path in train_dir.iterdir() if path.is_dir())
    train_dataset = CropFolderDataset(train_dir, class_names, train_transform, ignore_unknown=False)
    val_dataset = CropFolderDataset(val_dir, class_names, val_transform, ignore_unknown=True)

    num_classes = len(train_dataset.class_names)
    if num_classes <= 0:
        raise SystemExit("No classes found in crop dataset.")

    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, num_classes)

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
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.workers,
        pin_memory=device.type == "cuda",
    )

    class_counts = count_classes(train_dataset.targets, num_classes)
    class_weights = build_class_weights(class_counts).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights, label_smoothing=args.label_smoothing)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scaler = torch.cuda.amp.GradScaler(enabled=device.type == "cuda")

    history: list[dict] = []
    best_top1 = -1.0
    best_path = output_dir / "best_crop_classifier.pt"
    last_path = output_dir / "last_crop_classifier.pt"

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
            f"val_loss={row['val_loss']:.6f} val_top1={row['val_top1']:.6f}"
        )

        save_checkpoint(
            path=last_path,
            model=model,
            args=args,
            class_names=train_dataset.class_names,
            history=history,
        )
        if val_top1 > best_top1:
            best_top1 = val_top1
            save_checkpoint(
                path=best_path,
                model=model,
                args=args,
                class_names=train_dataset.class_names,
                history=history,
            )

    history_path = output_dir / "history.json"
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"best_top1={best_top1:.6f}")
    print(f"best_checkpoint={best_path}")


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


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
    def __init__(self, root: Path, class_names: list[str], transform, ignore_unknown: bool):
        self.root = root
        self.class_names = list(class_names)
        self.class_to_idx = {name: index for index, name in enumerate(self.class_names)}
        self.transform = transform
        self.samples: list[tuple[Path, int]] = []
        self.targets: list[int] = []

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
            raise SystemExit(f"No crop images found in {root}")

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

        with torch.cuda.amp.autocast(enabled=device.type == "cuda"):
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


if __name__ == "__main__":
    main()
