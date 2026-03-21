# Improvement Plan

## Scope

This plan is for improving the NorgesGruppen Data submission using only the data already present in the provided zip files:

- shelf images
- `annotations.json`
- reference product images and metadata

It assumes the submission constraints in `RULES.md` remain binding:

- sandbox-compatible package only
- no runtime installs
- no blocked imports/calls in `submission/run.py`
- max 3 weight files / 420 MB total
- practical inference budget inside the 300s sandbox timeout

The goal is not "train longer". The current evidence says the main gap is in fine-grained classification quality, data cleanliness, and validation fidelity.

## Current State

### What the repo is doing now

- Detector training/prep: `scripts/train_yolov8.py`
- Crop extraction: `scripts/extract_product_crops.py`
- Crop conflict filtering: `scripts/filter_conflicting_crops.py`
- Reference-tree build: `scripts/build_reference_by_category.py`
- Embedding-based outlier filtering: `scripts/flag_crop_outliers.py`
- Crop classifier training: `scripts/train_crop_classifier.py`
- Local score proxy: `scripts/evaluate_local.py`
- Packaged inference path: `submission/run.py`

### Current quantitative picture

Dataset facts from `data/reports/dataset_summary.json`:

| Item | Value |
| --- | ---: |
| shelf images | 248 |
| annotations | 22,731 |
| categories | 356 |
| median annotations per category | 28 |
| categories with <= 10 annotations | 115 |
| categories with <= 20 annotations | 164 |

Current split facts from `data/splits/default_split.json` and local counts:

| Item | Value |
| --- | ---: |
| train images | 198 |
| val images | 50 |
| train classes present | 338 |
| val classes present | 278 |
| train classes missing from val | 78 |
| val classes with <= 5 annotations | 91 |

Current crop filtering facts from `data/reports/next_run/train_crop_outliers.json`:

| Item | Value |
| --- | ---: |
| raw train crops | 18,320 |
| filtered train crops kept | 17,473 |
| removed | 847 |
| removed fraction | 4.62% |
| hard cross-category mismatches | 226 |

Reference coverage from `data/reports/next_run/reference_by_category_report.json`:

| Item | Value |
| --- | ---: |
| categories with reference coverage | 320 / 356 |
| unmatched categories | 36 |
| reference images | 631 |

Model behavior:

- Best crop-classifier validation top-1 so far: `0.879881`
- Latest scratch recrop run peaked at `0.873715` and then degraded while train top-1 kept rising
- Current local packaged submission is around:
  - detection AP50: `0.917 - 0.924`
  - classification mAP50: `0.698 - 0.708`
  - combined score: `0.852 - 0.859`
- Official competition score reported by the user: `0.8980`
- Current leaderboard best reported by the user: `0.9255`

### What this means

1. Detection is already reasonably strong. Classification is the main bottleneck.
2. The classifier is overfitting quickly.
3. The current validation regime is too weak to choose recipes confidently.
4. The crop pipeline is improved, but still not strong enough for fine-grained shelf products.
5. The current pipeline is not exploiting the provided reference images aggressively enough.

## Root-Cause Analysis

### 1. Data preparation is still too naive for fine-grained retail

Current crop extraction in `scripts/extract_product_crops.py` is still an exact bbox crop with optional padding. That leaves several problems:

- no aspect-preserving pad-to-square step before classifier training
- no controlled context policy by product family
- no explicit rejection of tag-like, shelf-edge, or background-heavy crops
- no near-duplicate filtering beyond exact file hash and very-high-IoU cross-category conflicts

The result is predictable: visually similar classes bleed into each other, and non-product or low-information crops contaminate training.

### 2. The classifier recipe is underpowered for the actual problem

The current classifier stack is basically:

- ConvNeXt/ResNet backbone
- weighted cross-entropy
- mild augmentation
- single split selection
- softmax-only final decision

This is too weak for:

- 356 classes
- heavy long-tail imbalance
- many classes with only a handful of examples
- same-brand / same-color / same-layout confusion
- noisy crops and incomplete references

The observed error pattern confirms this. High-support failures cluster in look-alike product families and size/variant confusions, not random misses.
The current packaged predictions show repeated swaps inside near-identical families such as coffee grind variants, package-size variants, and `unknown_product` being pulled into named classes.

### 3. Evaluation is not aligned tightly enough to the competition objective

The current local proxy is useful, but it is still:

- based on a single image-level split
- unstable for rare classes
- not the same as official hidden-set scoring
- not the same target as crop-classifier top-1

With only 50 validation images, a lot of recipe choices can look better or worse by noise alone.

### 4. The detector-classifier integration is still simplistic

The submission path uses:

- single-class detector output
- crop classifier relabeling
- fixed score blending
- fixed confidence/NMS settings

That leaves several easy gains unused:

- product-vs-junk rejection for false detections like price tags
- prototype similarity fusion from reference images
- threshold sweeps on the actual packaged path
- detector-side false-positive mining

## Best-of-Class Approaches That Fit This Repo

These are the highest-value approaches that fit the competition rules and the "no extra data" constraint.

### A. Reference-aware metric learning plus prototype retrieval

This is the single most promising classifier upgrade.

Why it fits this repo:

- we already have category reference images
- the hardest mistakes are between visually similar products
- prototype similarity is cheap to run inside the sandbox
- we still have one more allowed weight-like file slot for a precomputed prototype array

Recommended design:

1. Train an embedding model using train crops plus reference images.
2. Use supervised contrastive learning or ArcFace-style margin learning for the embedding space.
3. Build per-class prototypes from:
   - reference images when available
   - train-crop centroids for unmatched classes
4. At inference, fuse:
   - softmax probability
   - cosine similarity to class prototypes
   - detector confidence

This is much better suited to fine-grained retail than plain softmax alone.

### B. Long-tail-aware sampling and loss

The data is strongly long-tailed. Loss weighting alone is not enough.

Recommended upgrades:

- class-aware or repeat-factor sampling
- Balanced Softmax or Balanced Meta-Softmax
- optional two-stage classifier fine-tune:
  - stage 1: balanced sampler
  - stage 2: lower-LR calibration on full distribution

This should help low-count classes without making head classes dominate.

### C. Noise-robust training, not just noise filtering

The current outlier filter is a good start, but training should also be made less sensitive to remaining label noise.

Recommended upgrades:

- Generalized Cross Entropy or another noise-robust loss on flagged-risk classes
- confidence-based sample weighting from the reference/prototype agreement score
- keep a "suspect" subset and down-weight it instead of only hard deleting

### D. Stronger regularization and augmentation for fine-grained crops

The current augmentation recipe is too light.

Recommended upgrades:

- mixup
- CutMix
- stronger color/blur/compression augmentation
- aspect-preserving resize with pad-to-square instead of center-crop-driven distortion
- optional multi-view train crops:
  - tight crop
  - small padded crop

### E. Hard-negative mining for non-product false positives

This matters because the detector can still return shelf labels, tags, or low-information regions.

Recommended approach:

1. Run the detector on training images.
2. Collect high-confidence proposals with very low IoU to any GT box.
3. Build a binary product-vs-junk gate or rejector from:
   - true product crops
   - mined non-product negatives
4. Use the gate in `submission/run.py` to discard obvious junk before category assignment.

This uses only the provided data and directly addresses the "price tags in item classes" failure mode.

### F. Detector improvements focused on small dense shelves, not more classes

The current detector strategy is directionally right: strong single-class localization plus separate classification.

Recommended detector upgrades:

- continue with single-class detector as the main line
- run a real detector HPO sweep on `yolov8s/m/l`
- keep image size high
- test tiled inference only if timing stays within sandbox budget
- sweep confidence/NMS on the packaged path

Do not prioritize a 356-class detector first. With this data volume, that is likely worse than a strong localizer plus stronger classifier.

### G. Full-data retraining after selection

After selecting recipes by cross-validation, the final submission models should be retrained on all labeled shelf images, not just the train split.

With only 248 shelf images, leaving 50 aside permanently for the final model is too expensive.

## Priority Plan

### P0: Fix evaluation so we stop optimizing noise

This should happen before another long training cycle.

1. Replace single-split model selection with repeated image-level CV or 3-5 folds.
2. Score every candidate through the actual packaged inference path.
3. Track:
   - combined score
   - detection AP50
   - classification mAP50
   - per-class AP50
   - support-weighted per-family confusion
4. Add threshold sweeps for:
   - detector confidence
   - NMS IoU
   - classifier/detector score fusion alpha
   - optional rejector threshold

Success criterion:

- model choices stop being driven by single-run `val_top1`
- local ranking becomes stable across folds

### P1: Rebuild the crop pipeline properly

This is the highest-leverage data-prep work.

1. Version the crop pipeline by recipe:
   - tight crop
   - padded crop
   - padded + pad-to-square crop
2. Add near-duplicate detection:
   - perceptual hash
   - embedding-neighbor duplicates
   - cross-class duplicate audit
3. Add crop-quality rules:
   - tiny content ratio
   - extreme aspect ratio
   - low-texture / blank-like regions
   - extreme reference mismatch
4. Split flagged crops into:
   - hard delete
   - suspect / down-weight
5. Improve references:
   - fill unmatched categories where metadata matching can be improved
   - build train-crop prototypes for the remaining unmatched classes

Success criterion:

- lower confusion in look-alike families
- fewer obviously bad crops in per-class visual audits

### P2: Upgrade the classifier to a retrieval-aware fine-grained model

Recommended order:

1. Keep ConvNeXt as the base family.
2. Switch from pure softmax training to:
   - SupCon or margin-based embedding training
   - then classifier head fine-tune
3. Add prototype fusion:
   - one `.npy` file with class prototypes
   - runtime cosine similarity in `submission/run.py`
4. Add class-aware sampling and Balanced Softmax.
5. Add noise-aware weighting using outlier scores.
6. Replace center-crop inference with aspect-preserving resize/pad.

Success criterion:

- packaged classification mAP50 improves materially
- confusion between same-brand variants drops

### P3: Add a rejector for junk detections

This is the most targeted fix for price-tag and non-product issues.

1. Mine false-positive detections from shelf images.
2. Train a lightweight binary gate.
3. Run it only on detector boxes above a small confidence threshold.
4. Drop detections that score as non-product.

This should be implemented cheaply enough to keep submission runtime safe.

Success criterion:

- false positives drop without materially hurting recall
- packaged detection AP50 and combined score improve together

### P4: Run a serious detector search, but only after P0-P3

Detector work is still worth doing, just not first.

Recommended search:

- `yolov8s` single-class, high-res baseline
- `yolov8m` single-class, high-res candidate
- one larger model only if timing/size still fit
- optional tiled inference experiment

For each run, optimize by packaged combined score, not by training loss alone.

Success criterion:

- packaged detection AP50 improves without breaking runtime

### P5: Final model selection and retrain

1. Choose the best recipe from CV.
2. Retrain detector and classifier on all available labeled shelf images.
3. Export/package the final submission path.
4. Run:
   - security scan
   - local packaged score
   - size/file-count check
   - timing check on representative image sets

## What I Would Implement First

If the goal is fastest path to a score jump, I would do this exact sequence:

1. Add repeated packaged evaluation and threshold sweeps.
2. Rebuild crops with pad-to-square plus stronger quality filtering.
3. Add prototype-based retrieval fusion using the reference images.
4. Add class-aware sampling + Balanced Softmax.
5. Add hard-negative rejector for junk detections.
6. Retrain on all data after recipe selection.
7. Only then spend more time on larger detector sweeps.

## What Not To Do First

These are lower ROI right now:

- training longer with the same classifier recipe
- switching immediately to a much larger classifier backbone
- building a 356-class detector as the main line
- adding OCR before fixing the core crop/classifier pipeline
- online ensemble-heavy submission logic that risks the sandbox timeout

## Concrete Experiment Ladder

### Track 1: Validation and calibration

- Implement 3-fold packaged evaluation.
- Sweep:
  - detector confidence
  - NMS IoU
  - classifier alpha
  - rejector threshold if present

### Track 2: Crop pipeline

- Compare:
  - exact bbox
  - bbox + 5% pad
  - bbox + 10% pad
  - pad-to-square variants
- Add duplicate and quality audits.

### Track 3: Classifier

- Baseline: current best ConvNeXt recipe
- + balanced sampler
- + Balanced Softmax
- + prototype fusion
- + SupCon / metric-learning pretrain
- + noise-aware down-weighting

### Track 4: Rejector

- mine negatives
- train binary gate
- evaluate precision/recall tradeoff

### Track 5: Detector

- `yolov8s` single-class
- `yolov8m` single-class
- optional larger high-res candidate

## Expected Payoff

The most likely path to a meaningful score increase is:

- modest detector gain
- larger classification gain
- lower false-positive rate from a rejector

The current local numbers already show that a classifier improvement can move combined score materially. The biggest remaining upside is better category assignment on already-detected products.

## Sources

Primary sources that inform this plan:

- ConvNeXt: https://arxiv.org/abs/2201.03545
- Supervised Contrastive Learning: https://arxiv.org/abs/2004.11362
- Balanced Meta-Softmax for long-tail recognition: https://arxiv.org/abs/2007.10740
- Generalized Cross Entropy for noisy labels: https://arxiv.org/abs/1805.07836
- mixup: https://arxiv.org/abs/1710.09412
- CutMix: https://arxiv.org/abs/1905.04899
- ScaleNet for supermarket object proposals: https://openaccess.thecvf.com/content_iccv_2017/html/Qiao_ScaleNet_Guiding_Object_ICCV_2017_paper.html
- Fine-grained product recognition for shopping: https://openaccess.thecvf.com/content_iccv_2015_workshops/w12/html/George_Fine-Grained_Product_Class_ICCV_2015_paper.html
- IncreACO exemplar augmentation: https://openaccess.thecvf.com/content/WACV2021/html/Yang_IncreACO_Incrementally_Learned_Automatic_Check-Out_With_Photorealistic_Exemplar_Augmentation_WACV_2021_paper.html
- DeepACO / retail ACO pipeline context: https://openaccess.thecvf.com/content/CVPR2022W/AICity/html/Pham_DeepACO_A_Robust_Deep_Learning-Based_Automatic_Checkout_System_CVPRW_2022_paper.html
