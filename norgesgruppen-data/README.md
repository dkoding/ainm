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
- `scripts/summarize_dataset.py`: COCO dataset summary script.
- `scripts/make_splits.py`: reproducible train/validation split generator.
- `scripts/evaluate_local.py`: local hybrid-score approximation.
- `scripts/train_yolov8.py`: YOLOv8 data prep and training launcher.
- `scripts/prepare_reference_index.py`: product reference image indexer.
- `scripts/extract_product_crops.py`: crop extractor for second-stage classification experiments.

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

Example real-data outputs generated in this repository:

- `data/reports/dataset_summary.json`
- `data/splits/default_split.json`
- `data/reference/reference_index.json`
- `data/processed/yolov8/`
- `data/crops/by_category/`
- `runs/ngd/yolov8n_cpu_e1/`
- `dist/submission_trained.zip`

When you have weights ready, place them inside `submission/` and update `submission/submission_config.json`.

Supported default weight locations:

- Ultralytics:
  - `best.pt`
  - `model.pt`
  - `weights/best.pt`
- ONNX:
  - `model.onnx`
  - `weights/model.onnx`

If your trained model uses class indices that do not match the original COCO `category_id` values, place a generated `class_map.json` next to `run.py`. `scripts/train_yolov8.py` writes one automatically.

The default config still uses `detection_only: true` and `allow_empty_predictions: true`, which is appropriate for smoke testing and initial submission scaffolding. Before real leaderboard submissions, switch to a production config that loads a real model and fails fast if the weights are missing or incompatible.
