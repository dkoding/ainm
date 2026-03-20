# GPU Training And Submission Plan

## Goal

Train and package a materially stronger competition submission by assuming a CUDA-capable NVIDIA GPU is available and usable from the training environment.

This plan is written against the actual state of this repository and the real extracted competition data already present under `data/raw/`.

## Ground truth from the local data

Before training, use the extracted dataset rather than relying on the prose docs:

- Training annotations file: `data/raw/coco/train/annotations.json`
- Training images: `data/raw/coco/train/images/`
- Product reference images: `data/raw/reference/`

Real dataset findings already confirmed locally:

- `248` training images
- `22,731` annotations
- `356` categories
- category IDs are `0..355`
- `unknown_product` is category `355`

This means the training and submission flow should derive classes from `annotations.json`, not from the inconsistent doc text.

## Strategy

The fastest path to a strong score is:

1. Train a strong direct multi-class detector on GPU.
2. Score models through the actual submission path, not just the raw training loop.
3. Select the best detector by local combined score.
4. Only then consider a second-stage classification enhancement if classification is the limiting factor.

This matches the competition objective:

- `0.7 * detection_mAP@0.5`
- `0.3 * classification_mAP@0.5`

Detection quality is the bigger lever, so the first job is to get a detector that actually finds products reliably.

## Environment setup

Use a Linux path for the Python environment and caches, not `/mnt/d`, to avoid slow dataloading and broken virtualenv behavior on the Windows-mounted filesystem.

Recommended environment location:

- venv: `/tmp/ngd-gpu-venv`
- matplotlib cache: `/tmp/mpl`
- ultralytics cache/config: `/tmp/ultralytics`

Current host assumption for this repository:

- local training should see `NVIDIA RTX 3090` on CUDA device `0`
- GPU setup failures should be treated as environment regressions, not as the expected baseline

Install the sandbox-aligned package family:

```bash
python3 -m venv /tmp/ngd-gpu-venv
/tmp/ngd-gpu-venv/bin/pip install --upgrade pip setuptools wheel
/tmp/ngd-gpu-venv/bin/pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
/tmp/ngd-gpu-venv/bin/pip install numpy==1.26.4 Pillow==10.2.0 scipy==1.12.0 scikit-learn==1.4.0 pycocotools==2.0.7 ultralytics==8.1.0 timm==0.9.12 onnxruntime-gpu==1.20.0 opencv-python-headless==4.9.0.80 albumentations==1.3.1 ensemble-boxes==1.0.9 supervision==0.18.0 safetensors==0.4.2
```

Verify GPU visibility:

```bash
MPLCONFIGDIR=/tmp/mpl YOLO_CONFIG_DIR=/tmp/ultralytics /tmp/ngd-gpu-venv/bin/python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.device_count())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no-gpu")
PY
```

Expected outcome:

- `torch.cuda.is_available()` should be `True`
- GPU name should report the available NVIDIA device

## Dataset preparation

Regenerate and lock the training artifacts once before running experiments:

```bash
cd /mnt/d/work/ainm/norgesgruppen-data

python3 scripts/summarize_dataset.py \
  data/raw/coco/train/annotations.json \
  --images-dir data/raw/coco/train/images \
  --output data/reports/dataset_summary.json

python3 scripts/make_splits.py \
  data/raw/coco/train/annotations.json \
  --output data/splits/default_split.json \
  --group-mode random \
  --val-fraction 0.2 \
  --seed 42

python3 scripts/train_yolov8.py \
  data/raw/coco/train/annotations.json \
  data/raw/coco/train/images \
  --split data/splits/default_split.json \
  --workspace data/processed/yolov8 \
  --prepare-only \
  --submission-dir submission
```

What this produces:

- `data/reports/dataset_summary.json`
- `data/splits/default_split.json`
- `data/processed/yolov8/`
- `submission/class_map.json`

These artifacts should be treated as the canonical training layout for the first phase.

## Experiment ladder

Run three primary detector experiments and compare them with the repo’s local evaluator.

### Experiment 1

Balanced small model baseline:

```bash
MPLCONFIGDIR=/tmp/mpl YOLO_CONFIG_DIR=/tmp/ultralytics /tmp/ngd-gpu-venv/bin/python scripts/train_yolov8.py \
  data/raw/coco/train/annotations.json \
  data/raw/coco/train/images \
  --split data/splits/default_split.json \
  --workspace data/processed/yolov8 \
  --submission-dir submission \
  --model yolov8s.pt \
  --epochs 100 \
  --imgsz 960 \
  --batch 16 \
  --device 0 \
  --project runs/ngd \
  --name yolov8s_960_e100 \
  --workers 8
```

### Experiment 2

Likely sweet spot:

```bash
MPLCONFIGDIR=/tmp/mpl YOLO_CONFIG_DIR=/tmp/ultralytics /tmp/ngd-gpu-venv/bin/python scripts/train_yolov8.py \
  data/raw/coco/train/annotations.json \
  data/raw/coco/train/images \
  --split data/splits/default_split.json \
  --workspace data/processed/yolov8 \
  --submission-dir submission \
  --model yolov8m.pt \
  --epochs 100 \
  --imgsz 960 \
  --batch 12 \
  --device 0 \
  --project runs/ngd \
  --name yolov8m_960_e100 \
  --workers 8
```

### Experiment 3

High-recall larger model:

```bash
MPLCONFIGDIR=/tmp/mpl YOLO_CONFIG_DIR=/tmp/ultralytics /tmp/ngd-gpu-venv/bin/python scripts/train_yolov8.py \
  data/raw/coco/train/annotations.json \
  data/raw/coco/train/images \
  --split data/splits/default_split.json \
  --workspace data/processed/yolov8 \
  --submission-dir submission \
  --model yolov8l.pt \
  --epochs 80 \
  --imgsz 1280 \
  --batch 6 \
  --device 0 \
  --project runs/ngd \
  --name yolov8l_1280_e80 \
  --workers 8
```

Adjustment rules:

- If VRAM is tight, halve batch size first.
- If VRAM is abundant, increase batch size modestly.
- Keep `imgsz` high enough to preserve small-object detail in dense shelves.
- Prefer `yolov8m @ 960` as the first serious candidate if compute is limited.

## Model selection workflow

Do not choose a model by Ultralytics training output alone.

Each trained model must be evaluated through the actual submission path:

```bash
cp runs/ngd/<RUN_NAME>/weights/best.pt submission/best.pt

MPLCONFIGDIR=/tmp/mpl YOLO_CONFIG_DIR=/tmp/ultralytics /tmp/ngd-gpu-venv/bin/python submission/run.py \
  --input data/processed/yolov8/val/images \
  --output data/reports/<RUN_NAME>_predictions.json

python3 scripts/evaluate_local.py \
  data/raw/coco/train/annotations.json \
  data/reports/<RUN_NAME>_predictions.json \
  --split data/splits/default_split.json \
  --output data/reports/<RUN_NAME>_eval.json
```

Track these fields for every run:

- `run_name`
- detection AP
- classification mAP
- combined score
- average inference time
- `best.pt` size
- final zip size

The repository now includes `scripts/score_submission_run.py` to automate this staging, scoring, timing, and packaging loop against the real `submission/run.py` path.

The winning model is the one with the best local combined score while still fitting the submission runtime and packaging constraints.

## Recommended first choice

If only one serious experiment can be run first, use:

```bash
MPLCONFIGDIR=/tmp/mpl YOLO_CONFIG_DIR=/tmp/ultralytics /tmp/ngd-gpu-venv/bin/python scripts/train_yolov8.py \
  data/raw/coco/train/annotations.json \
  data/raw/coco/train/images \
  --split data/splits/default_split.json \
  --workspace data/processed/yolov8 \
  --submission-dir submission \
  --model yolov8m.pt \
  --epochs 100 \
  --imgsz 960 \
  --batch 12 \
  --device 0 \
  --project runs/ngd \
  --name yolov8m_960_e100 \
  --workers 8
```

Why:

- `m` is large enough to matter on this dense shelf task
- `960` keeps more detail than `640`
- it is much more practical than jumping straight to the largest model

## Classification improvement phase

Only do this after the detector is already nontrivial.

Useful local assets already available:

- crop generator: `scripts/extract_product_crops.py`
- reference index: `data/reference/reference_index.json`
- crop output path: `data/crops/by_category/`

Potential second-phase work:

- train a crop classifier on extracted shelf crops
- use product reference images for embedding-based re-ranking
- re-rank detector class outputs using crop similarity to reference images

Important caveat from the real dataset:

- the extracted training annotations do not include `product_code` or `product_name`
- this makes reference-image alignment less direct than the prose docs imply

So the classification enhancement phase should be treated as an optimization phase, not the first milestone.

## Submission packaging

Once the best run is selected:

1. Copy the trained checkpoint into `submission/best.pt`
2. Keep `submission/class_map.json`
3. Ensure `submission/submission_config.json` uses:
   - `detection_only: false`
   - `allow_empty_predictions: false`
4. Build and verify the zip

Command:

```bash
MPLCONFIGDIR=/tmp/mpl YOLO_CONFIG_DIR=/tmp/ultralytics /tmp/ngd-gpu-venv/bin/python scripts/preflight_submission.py \
  submission \
  --image-dir data/processed/yolov8/val/images \
  --output-zip dist/submission_final.zip
```

Artifacts to expect:

- `submission/best.pt`
- `submission/class_map.json`
- `dist/submission_final.zip`

Upload `dist/submission_final.zip` on the competition submit page.

## Version-compatibility fallback

If training happens with package versions that differ from the competition sandbox and `.pt` compatibility becomes risky:

1. Export ONNX with opset `17`
2. Switch the submission config to the ONNX backend
3. Validate the ONNX path locally before submitting

This is the safer compatibility path when direct `.pt` loading is uncertain.

## Practical success criteria

The plan is working if:

- GPU is visible to `torch`
- the `yolov8m_960_e100` run completes
- `submission/run.py` produces non-empty predictions on validation images
- `scripts/evaluate_local.py` reports a non-zero combined score
- `scripts/preflight_submission.py` builds a valid weighted zip

## Immediate next actions

1. Create the CUDA venv under `/tmp/ngd-gpu-venv`
2. Confirm `torch.cuda.is_available() == True`
3. Run `yolov8m_960_e100`
4. Score it through `submission/run.py`
5. Compare against `yolov8s_960_e100`
6. Only then decide whether `yolov8l_1280_e80` is worth the extra cost

## Bottom line

The best near-term route is:

- use a sandbox-compatible CUDA environment
- train a serious YOLOv8 detector first
- rank models by the local combined score produced through the real submission path
- package the winner with `submission/best.pt` and `submission/class_map.json`
- only invest in second-stage classification once detection is already strong
