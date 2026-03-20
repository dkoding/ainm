# NorgesGruppen Data

This directory contains a submission template for the offline zip task.

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

- `submission/run.py`: zip-safe baseline that can use a local Ultralytics `.pt` weight file if you place one next to it.
- `submission/submission_config.json`: simple JSON config for detection-only mode and confidence threshold.
- `scripts/check_submission.py`: local validator for zip structure and file limits.

Manual blockers:

- The training data and product reference image downloads require your logged-in AINM account. I cannot fetch them from here.
- You still need to train or choose weights. The included baseline falls back to empty predictions if no supported `.pt` file is present.

Quick start:

```bash
cd norgesgruppen-data
python3 scripts/check_submission.py submission
```

When you have weights ready, place one of these inside `submission/`:

- `best.pt`
- `model.pt`
- `weights/best.pt`

The default config uses `detection_only: true`, which sets all `category_id` values to `0`. That matches the docs for a detection-first baseline and avoids wrong product IDs from generic pretrained weights.
