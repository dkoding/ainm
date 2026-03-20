# Task Tracker

## Repository Implementation

- [x] Create `TASKS.md` and keep it updated while implementing the plan.
- [x] Harden `submission/run.py` with explicit backend selection, class mapping, ONNX support, and fail-fast loading.
- [x] Expand `submission/submission_config.json` for production and smoke-test workflows.
- [x] Extend `scripts/check_submission.py` to validate directories and zip files, mirror more of the documented security checks, and verify zip-root structure.
- [x] Add `scripts/smoke_submission.py` to run `submission/run.py` locally and validate the output schema.
- [x] Add `scripts/build_submission.py` to create a correctly structured submission zip.
- [x] Add `scripts/preflight_submission.py` to chain validation, smoke testing, and zip creation.
- [x] Add `scripts/summarize_dataset.py` to inspect the COCO dataset and emit summary statistics.
- [x] Add `scripts/make_splits.py` to create reproducible train/validation splits.
- [x] Add `scripts/evaluate_local.py` to approximate the official hybrid score locally.
- [x] Add `scripts/train_yolov8.py` to prepare YOLO training data and launch a baseline training run.
- [x] Add `scripts/prepare_reference_index.py` to index the product reference images and metadata.
- [x] Add `scripts/extract_product_crops.py` to create crop datasets for second-stage classification experiments.
- [x] Update `README.md` to document the new workflow.
- [x] Run local verification for the implemented scripts and the submission scaffold.

Verification note:

- The submission preflight passes locally.
- The dataset summary, split generation, local evaluation, YOLO prep, and reference indexing scripts were exercised on a synthetic COCO fixture.
- `scripts/extract_product_crops.py` is implemented and now fails with a clear message if Pillow is not installed in the local environment.

## External / Data-Dependent Work

- [ ] Download `NM_NGD_coco_dataset.zip` from the competition site.
- [ ] Download `NM_NGD_product_images.zip` from the competition site.
- [ ] Train real model weights on the downloaded dataset.
- [ ] Benchmark local validation metrics on real predictions.
- [ ] Submit a validated zip to the competition and compare leaderboard results.
