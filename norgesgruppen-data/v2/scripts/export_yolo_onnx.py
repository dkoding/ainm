from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a YOLO checkpoint to ONNX for sandbox-safe submission.")
    parser.add_argument("weights", type=Path, help="Path to the trained YOLO .pt checkpoint.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "submission" / "model.onnx",
        help="Destination ONNX path. Defaults to submission/model.onnx",
    )
    parser.add_argument("--imgsz", type=int, default=1280, help="Inference/export image size.")
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version. Must stay <= 20 for the sandbox.")
    parser.add_argument("--half", action="store_true", help="Export FP16 weights when supported by the current device.")
    parser.add_argument("--device", default="cuda", help="Ultralytics export device, for example cuda or cpu.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weights_path = args.weights.resolve()
    output_path = args.output.resolve()
    if not weights_path.exists():
        raise SystemExit(f"Missing weights file: {weights_path}")

    add_local_ultralytics_path()

    from ultralytics import YOLO

    model = YOLO(str(weights_path))
    exported_path = Path(
        model.export(
            format="onnx",
            imgsz=args.imgsz,
            opset=args.opset,
            simplify=False,
            dynamic=False,
            nms=False,
            half=args.half,
            device=args.device,
        )
    ).resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if exported_path != output_path:
        shutil.copy2(exported_path, output_path)
    print(f"OK: {output_path}")


def add_local_ultralytics_path() -> None:
    for repo_root in (PROJECT_ROOT, PROJECT_ROOT.parent):
        for folder_name in (".vendor_export", ".vendor_ultra"):
            candidate = repo_root / folder_name
            if candidate.exists() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))


if __name__ == "__main__":
    main()
