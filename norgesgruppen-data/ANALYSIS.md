# NorgesGruppen Data Analysis

## Scope

This document compares the official NorgesGruppen Data docs with the current local scaffolding in this repository and turns that comparison into a concrete implementation plan.

Docs reviewed:

- https://app.ainm.no/docs/norgesgruppen-data/overview
- https://app.ainm.no/docs/norgesgruppen-data/submission
- https://app.ainm.no/docs/norgesgruppen-data/scoring
- https://app.ainm.no/docs/norgesgruppen-data/examples

## What the task actually is

The competition task is an offline object detection and product identification problem:

- Input at submission time: JPEG shelf images in `/data/images`, named like `img_00042.jpg`.
- Output at submission time: a JSON array written to the provided `--output` path.
- Each prediction row must contain:
  - `image_id`
  - `category_id`
  - `bbox` in COCO `[x, y, w, h]` format
  - `score` in `[0, 1]`
- Submission artifact: a `.zip` with `run.py` at the zip root.
- Runtime environment: Python 3.11, 4 vCPU, 8 GB RAM, NVIDIA L4 GPU, CUDA 12.4, no network, 300 second timeout.
- Packaging limits: max 420 MB uncompressed, max 1000 files, max 10 Python files, max 3 weight files, restricted file extensions.

Scoring is hybrid:

- `0.7 * detection_mAP@0.5`
- `0.3 * classification_mAP@0.5`

This means detection quality is the primary driver, but correct class assignment is still worth a large enough fraction that a serious solution cannot stop at detection-only if the goal is to be competitive.

## Dataset and modeling implications

From the docs:

- Training dataset: about 248 shelf images and about 22,700 annotations.
- Product reference images: about 327 products with multi-angle views plus `metadata.json`.
- Shelf images come from 4 store sections.
- The training annotations are COCO-style and include `product_code`, `product_name`, and `corrected`.

Practical implications:

- The dataset is small in image count but dense in objects per image.
- A submission-ready solution needs to be optimized for crowded-scene detection, not generic single-object classification.
- The reference-image pack is likely useful for class disambiguation or re-ranking, but detection quality is still the first priority because of the 70/30 score split.
- Because the runtime is offline and time-limited, the submission package must contain everything it needs to infer locally without downloads.

## Important doc inconsistencies and ambiguities

The docs are mostly clear, but there are a few inconsistencies that matter for implementation:

1. Category count is inconsistent.
   - Some text says 356 categories with IDs `0-355`.
   - Other text and examples imply 357 IDs `0-356`.
   - The annotation snippet includes `unknown_product` with ID `356`.
   - The YOLO example says to fine-tune with `nc=357`.

2. Detection-only guidance is slightly awkward.
   - The docs say detection-only submissions can set `category_id: 0` for all predictions.
   - But the annotation examples also show `0` as a real category ID.

3. The examples are baseline-oriented, not production-oriented.
   - They are good for format validation.
   - They are not enough to guarantee compatibility, score quality, or safe failure behavior in real submissions.

Implementation consequence:

- Do not hardcode the class count from the prose docs.
- Derive the number of classes and the ID mapping from `annotations.json`.
- Treat the current detection-only mode as a bootstrap baseline, not as a final scoring strategy.

## Current scaffold inventory

The repository currently contains:

- `README.md`
- `submission/run.py`
- `submission/submission_config.json`
- `scripts/check_submission.py`

Observed behavior:

- `python3 scripts/check_submission.py submission` passes.
- `python3 submission/run.py --input ... --output ...` runs successfully in the no-weights path and writes `[]`.

That means the scaffold is currently a valid structural starting point, but not a competitive solution.

## Comparison: docs vs current scaffolding

| Requirement | Current scaffold | Status | Notes |
| --- | --- | --- | --- |
| Zip submission with `run.py` at zip root | `submission/` is structured so its contents can become the zip root | Partial | Correct idea, but no actual zip build script yet |
| `run.py --input --output` contract | Implemented in `submission/run.py` | Good | Matches docs |
| JSON output format | Implemented | Good | Uses required fields |
| Detection-only baseline | Implemented via `detection_only` config | Good | Useful for smoke tests |
| GPU auto-detection | Implemented with `torch.cuda.is_available()` | Good | Matches docs |
| Allowed imports in submission code | `run.py` uses safe standard modules plus runtime imports of `torch` and `ultralytics` | Mostly good | No obvious banned imports in scaffold |
| Package/file-count/size checks | `scripts/check_submission.py` covers many limits | Partial | Does not mirror the full server-side security scan |
| Support for official recommended model formats | Only Ultralytics `.pt` is supported today | Gap | No ONNX, no `safetensors`, no custom `state_dict` loader |
| Real inference path with trained weights | Not present | Gap | No weights, no training pipeline |
| Classification-ready model path | Not present | Gap | Default mode intentionally throws away class information |
| Local scoring loop that mirrors official score | Not present | Gap | No detection/classification mAP evaluator |
| Submission build and verification workflow | Not present | Gap | No zip creation script or preflight smoke harness |
| Security-scan parity | Not present | Gap | No checks for banned imports/calls, symlinks, binaries, or path traversal |

## What the current scaffold does well

The current scaffold is useful in the following ways:

- It correctly centers the work around the offline zip contract rather than an HTTP service.
- It uses a minimal `run.py` with a submission-safe configuration file format (`json` instead of `yaml`).
- It already matches the documented CLI contract and output schema.
- It includes a local validator for file counts, extensions, and size limits.
- It has a detection-only mode, which is an appropriate first submission baseline if the goal is only to validate packaging and execution.

This is a good scaffold for "can I upload a valid artifact?" but not yet for "can I compete well on the leaderboard?"

## Main gaps and risks

### 1. No trained model, no data pipeline, no evaluation loop

This is the biggest gap. The current repository does not include:

- downloaded competition data
- dataset preparation code
- train/validation splits
- training scripts
- evaluation scripts
- model weights

Without these, the repository is only a submission shell.

### 2. The current fallback behavior can silently produce a zero-score submission

`submission/run.py` tries candidate weight files and falls back to `EmptyPredictor()` if loading fails. That is convenient for local smoke testing, but dangerous for real submissions:

- if the weight file is missing, incompatible, or corrupted
- and the load exception is swallowed
- the package still runs and uploads successfully
- but the result is likely a `0.0` score

For a real competition workflow, this should become fail-fast or be explicitly configurable.

### 3. The scaffold only supports one narrow inference backend

The docs explicitly recommend several compatibility paths:

- pinned Ultralytics `.pt`
- ONNX
- custom PyTorch code with `state_dict`
- `safetensors`

The scaffold currently supports only one of those. That is too narrow for a production submission path.

### 4. No local approximation of the official score

The official score is hybrid. Without a local evaluator, it is too easy to optimize only for one component and discover regressions via paid-for leaderboard attempts.

This is especially risky because:

- submissions are limited per day
- public leaderboard feedback is incomplete
- private-final ranking can differ from the public board

### 5. No plan for using the reference images

The docs provide a second downloadable artifact containing product reference images and metadata. The current scaffold does not consider it at all.

That is acceptable for a first detector baseline, but likely leaves classification performance on the table.

### 6. Validator coverage is incomplete

The local validator does not currently check several server-side failure modes mentioned in the docs:

- banned imports
- banned dynamic calls such as `eval` / `exec`
- disallowed binaries
- symlinks
- path traversal
- zip-root verification from an actual built archive

This means a locally "passing" submission can still fail remotely.

## Recommended solution strategy

The most pragmatic path is not to start with a complex two-stage system. The first serious target should be a strong end-to-end detector/classifier that already respects the submission environment.

Recommended order:

1. Build a strong single-model baseline first.
   - Fine-tune YOLOv8 or another sandbox-compatible detector on the competition COCO data.
   - Train with the real class count derived from `annotations.json`.
   - Establish a reliable local score before experimenting further.

2. Harden the inference and packaging path second.
   - Add ONNX support and a strict preflight validator.
   - Make failures explicit instead of silently returning empty predictions.

3. Add classification improvements only after the baseline is stable.
   - Use the product reference images for class re-ranking, retrieval, or a second-stage crop classifier if class confusion remains the limiting factor.

Why this order is correct:

- The scoring weights make detection the larger lever.
- A simple, fast, robust detector is easier to package and debug than a multi-stage system.
- The dataset is small enough that data handling, validation, and metric discipline matter as much as architecture choice.

## Proposed target architecture

### Phase A target

A single-stage detector that outputs final boxes and class IDs directly.

Good candidates from the documented sandbox:

- YOLOv8m / YOLOv8l
- RT-DETR if it fits the packaging/runtime budget
- torchvision detectors only if they perform competitively in local evaluation

Preferred first implementation:

- train a YOLOv8 family model with `nc = len(categories)`
- export best model either as:
  - pinned Ultralytics `.pt`, or
  - ONNX if compatibility issues appear
- run inference on GPU in `run.py`
- emit predictions directly in the required format

### Phase B target

Add a second-stage classification or retrieval step only if local analysis shows that:

- detection mAP is already strong
- but classification mAP is materially lagging

Possible second-stage options:

- crop classifier trained on shelf-product crops
- embedding-based retrieval against product reference images
- detector output re-ranking using reference-image similarity plus detector confidence

This second phase should be justified by local metrics, not built speculatively.

## Concrete implementation plan

### Phase 0: Unblock data access

Blocked externally:

- The docs state the datasets must be downloaded from the competition website while logged in.
- That cannot be completed from this repository alone.

Actions:

1. Download:
   - `NM_NGD_coco_dataset.zip`
   - `NM_NGD_product_images.zip`
2. Place them under a local data directory outside the final submission zip.
3. Extract and verify:
   - image count
   - annotation count
   - category count
   - reference-image metadata

Deliverables:

- `data/raw/...`
- a small script or notebook that prints dataset summary stats

### Phase 1: Build the local evaluation foundation

Actions:

1. Parse `annotations.json` and generate:
   - category lookup
   - image metadata table
   - per-class counts
   - per-section counts
2. Create train/validation splits.
   - Prefer grouped or section-aware splits.
   - Avoid leaking near-duplicate shelf conditions between train and validation if possible.
3. Implement a local evaluator that mirrors the official score:
   - detection mAP@0.5 with category ignored
   - classification mAP@0.5 with category enforced
   - combined weighted score

Deliverables:

- `scripts/summarize_dataset.py`
- `scripts/make_splits.py`
- `scripts/evaluate_local.py`
- saved split definitions and baseline metrics

### Phase 2: Harden the submission runtime

Actions:

1. Refactor `submission/run.py` into an explicit backend architecture.
   - `UltralyticsPredictor`
   - `OnnxPredictor`
   - optional custom PyTorch predictor if needed
2. Replace silent empty fallback with stricter behavior.
   - Keep empty-output mode only for deliberate smoke tests.
   - For production config, fail if the configured model cannot load.
3. Add more explicit configuration fields:
   - backend type
   - weights path
   - confidence threshold
   - NMS / max detections
   - image size
   - detection-only toggle for validation-only submissions
4. Add a local smoke harness that:
   - creates a temporary input directory
   - runs `submission/run.py`
   - validates the output schema

Deliverables:

- hardened `submission/run.py`
- expanded `submission/submission_config.json`
- local runtime smoke test script

### Phase 3: Produce a real baseline model

Actions:

1. Start with a supported detector family with straightforward export/inference.
2. Fine-tune on the shelf dataset with all classes enabled.
3. Track:
   - validation combined score
   - detection mAP
   - classification mAP
   - runtime per image / per batch
   - final model size
4. Compare:
   - detection-only inference
   - full classification inference
   - different image sizes and confidence thresholds

Recommendation:

- Start with YOLOv8m or YOLOv8l rather than the smallest model.
- Use FP16 where it improves speed/size without harming score.

Deliverables:

- first real trained weights
- reproducible training config
- baseline score report

### Phase 4: Improve classification quality

Actions:

1. Inspect confusion matrix and failure cases.
2. Determine whether classification is the bottleneck after detection stabilizes.
3. If needed, add one of:
   - detector fine-tuning improvements
   - crop classifier
   - reference-image retrieval
   - test-time re-ranking
4. Validate that the extra stage still fits:
   - 300 second timeout
   - 8 GB RAM
   - 420 MB package budget

Deliverables:

- improved classification strategy with measured lift over the single-stage baseline

### Phase 5: Extend preflight validation to match the docs

Actions:

1. Extend `scripts/check_submission.py` to detect:
   - banned imports
   - banned calls where statically detectable
   - symlinks
   - path traversal
   - non-allowed binaries or file signatures
2. Add a zip build script that creates the archive correctly.
3. Validate the actual built zip, not just the source directory.
4. Add a final pre-submission checklist:
   - zip structure
   - weight size
   - package count
   - smoke run
   - output schema

Deliverables:

- stronger validator
- repeatable zip build script
- one-command preflight

### Phase 6: Submission strategy

Actions:

1. Use the first submission only to validate infrastructure compatibility.
2. Avoid spending daily submissions on experiments that have not beaten the local baseline.
3. Keep a changelog of:
   - model version
   - score deltas
   - runtime
   - package size
4. Explicitly choose the final-evaluation submission instead of assuming the public-best one is safest.

This matters because the docs specify:

- only 3 submissions per day
- only 2 in flight at once
- public and private evaluation sets differ

## Recommended immediate next steps

If the goal is to move from scaffold to working solution, the next steps should be:

1. Download and inspect the real datasets.
2. Implement local dataset summary and scoring scripts before training anything.
3. Refactor the submission runtime to support a production backend and fail-fast behavior.
4. Train a first end-to-end detector/classifier baseline.
5. Submit only after local scoring and packaging checks are in place.

## Bottom line

The current repository is a valid submission scaffold, not a solved competition entry.

It already handles:

- the offline zip-oriented shape of the task
- the required `run.py` CLI contract
- the output schema
- a basic structural validator
- a detection-only smoke-test path

It does not yet handle:

- data ingestion
- training
- real inference weights
- official-like local scoring
- robust packaging validation
- production-safe failure handling
- classification optimization using the reference images

The correct approach is to keep the current scaffold as the packaging nucleus, then build the missing modeling, evaluation, and preflight layers around it in that order.
