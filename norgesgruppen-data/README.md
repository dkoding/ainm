# NorgesGruppen Data

This directory contains a submission scaffold and local tooling for the offline zip task.

What the docs require:

- Upload a `.zip` file, not an HTTPS endpoint.
- `run.py` must be at the root of the zip.
- The runtime command is:

```bash
python run.py --input /data/images --output /output/predictions.json
```

- Output must be a JSON array of detections with `image_id`, `category_id`, `bbox`, and `score`.
- Sandbox is offline, GPU-backed, Python 3.11, 300 second timeout.
- Allowed file types are restricted and several imports are blocked.

What is included here:

- `submission/run.py`: submission entry point with `ultralytics` and ONNX backends, class mapping, and configurable fail-fast behavior.
- `submission/submission_config.json`: JSON config for backend selection, thresholds, class mapping, and smoke-test fallback behavior.
- `scripts/check_submission.py`: local validator for directories or built zips, including file limits and a lightweight static security scan.
- `scripts/smoke_submission.py`: local runner that executes `submission/run.py` and validates the output schema.
- `scripts/build_submission.py`: zip builder that keeps `run.py` at the archive root.
- `scripts/preflight_submission.py`: one-command local preflight for validate → smoke → build → validate.
- `scripts/score_submission_run.py`: stage a trained checkpoint into `submission/`, run the real submission path, score it locally, and record runtime/package metrics.
- `scripts/make_cv_splits.py`: generate repeated image-level or group-level cross-validation folds.
- `scripts/sweep_submission_cv.py`: score the real packaged submission path over CV folds while sweeping thresholds and classifier fusion settings.
- `scripts/summarize_dataset.py`: COCO dataset summary script.
- `scripts/make_splits.py`: reproducible train/validation split generator.
- `scripts/evaluate_local.py`: local hybrid-score approximation.
- `scripts/train_yolov8.py`: YOLOv8 data prep and training launcher.
- `scripts/sweep_yolov8_experiments.py`: reproducible detector sweep helper built on top of `train_yolov8.py` and `score_submission_run.py`.
- `scripts/prepare_reference_index.py`: product reference image indexer.
- `scripts/extract_product_crops.py`: crop extractor for second-stage classification experiments, including square-padding support.
- `scripts/audit_crop_duplicates.py`: perceptual near-duplicate audit for extracted crops.
- `scripts/flag_crop_outliers.py`: embedding-based crop-quality filter with separate hard-delete and suspect manifests.
- `scripts/build_classifier_prototypes.py`: build class prototypes for submission-time classifier/prototype fusion, with optional product/junk auxiliary prototypes.
- `scripts/mine_detector_hard_negatives.py`: mine detector false positives as junk negatives for rejector experiments.
- `scripts/finalize_submission.py`: final local verify -> score -> package wrapper.

Manual blockers:

- The training data and product reference image downloads require your logged-in AINM account. I cannot fetch them from here.
- You still need to download the real datasets and train or choose weights.

Quick start:

```bash
cd norgesgruppen-data
python3 scripts/preflight_submission.py submission
```

When `submission/` contains real model weights that depend on packages like `ultralytics`, `torch`, `onnxruntime`, or `Pillow`, run the tooling from a matching environment instead of bare system Python. The competition sandbox package family is documented on the submission page; locally, the same scripts can be invoked as:

```bash
/path/to/python scripts/preflight_submission.py submission
```

Dataset workflow:

```bash
python3 scripts/summarize_dataset.py /path/to/annotations.json --images-dir /path/to/images
python3 scripts/make_splits.py /path/to/annotations.json --output data/splits/default_split.json
python3 scripts/train_yolov8.py /path/to/annotations.json /path/to/images --split data/splits/default_split.json --prepare-only
```

GPU scoring workflow:

```bash
python3 scripts/score_submission_run.py \
  /path/to/annotations.json \
  /path/to/val/images \
  --split data/splits/default_split.json \
  --weights runs/ngd/yolov8m_960_e100/weights/best.pt \
  --predictions-output data/reports/yolov8m_960_e100_predictions.json \
  --output data/reports/yolov8m_960_e100_eval.json \
  --output-zip dist/yolov8m_960_e100.zip \
  --fail-on-empty
```

Cross-validation and improvement workflow:

```bash
python3 scripts/make_cv_splits.py \
  /path/to/annotations.json \
  --output-dir data/splits/cv/default \
  --fold-count 3 \
  --repeats 2

python3 scripts/sweep_submission_cv.py \
  /path/to/annotations.json \
  /path/to/images \
  submission \
  --cv-manifest data/splits/cv/default/manifest.json \
  --confidence-thresholds 0.03 0.05 0.07 \
  --nms-iou-thresholds 0.45 0.50 0.55 \
  --classifier-score-alphas 0.4 0.5 0.6
```

Crop-quality workflow:

```bash
python3 scripts/extract_product_crops.py \
  /path/to/annotations.json \
  /path/to/images \
  data/crops/train_by_category \
  --split data/splits/default_split.json \
  --split-name train \
  --padding 0.05 \
  --pad-to-square \
  --manifest data/crops/train_crop_manifest.json

python3 scripts/audit_crop_duplicates.py \
  data/crops/train_crop_manifest.json

python3 scripts/flag_crop_outliers.py \
  data/crops/train_crop_manifest.json \
  runs/crop_classifier/best_crop_classifier.pt \
  --reference-root data/crops/reference_by_category \
  --keep-suspect
```

Prototype and rejector workflow:

```bash
python3 scripts/mine_detector_hard_negatives.py \
  /path/to/annotations.json \
  /path/to/images \
  submission \
  --split data/splits/default_split.json \
  --split-name train

python3 scripts/build_classifier_prototypes.py \
  runs/crop_classifier/best_crop_classifier.pt \
  --train-manifest data/crops/train_crop_manifest_filtered.json \
  --reference-root data/crops/reference_by_category \
  --junk-manifest data/crops/junk_negatives_manifest.json \
  --output submission/class_prototypes.npy
```

Final packaging workflow:

```bash
python3 scripts/finalize_submission.py \
  --submission-dir submission \
  --output-zip dist/submission_final.zip \
  --annotations /path/to/annotations.json \
  --image-dir /path/to/val/images \
  --split data/splits/default_split.json \
  --split-name val \
  --fail-on-empty
```

Example real-data outputs generated in this repository:

- `data/reports/dataset_summary.json`
- `data/splits/default_split.json`
- `data/reference/reference_index.json`
- `data/processed/yolov8/`
- `data/crops/by_category/`
- `runs/ngd/yolov8n_cpu_e1/`
- `dist/submission_trained.zip`

When you have weights ready, place them inside `submission/` and update `submission/submission_config.json`.
The current submission path supports an ONNX detector, a crop-classifier checkpoint, and a single `.npy` prototype matrix within the competition's 3-weight-file limit.

Supported default weight locations:

- Ultralytics:
  - `best.pt`
  - `model.pt`
  - `weights/best.pt`
- ONNX:
  - `model.onnx`
  - `weights/model.onnx`

If your trained model uses class indices that do not match the original COCO `category_id` values, place a generated `class_map.json` next to `run.py`. `scripts/train_yolov8.py` writes one automatically.

The checked-in defaults are production-oriented: `detection_only: false` and `allow_empty_predictions: false`. Use `scripts/smoke_submission.py` without `--fail-on-empty` when you only want schema validation on a placeholder scaffold.
