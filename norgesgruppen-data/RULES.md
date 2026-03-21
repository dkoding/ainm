# RULES

Use this file as the working rulebook for this repo, especially before any submission, packaging, or `run.py` change.

Primary source:
- Official submission docs: `https://app.ainm.no/docs/norgesgruppen-data/submission`

## Submission Structure

- The submission zip must contain `run.py` at the archive root.
- Allowed extra files include weights and helper code.
- Allowed file types: `.py`, `.json`, `.yaml`, `.yml`, `.cfg`, `.pt`, `.pth`, `.onnx`, `.safetensors`, `.npy`
- Max files: `1000`
- Max Python files: `10`
- Max weight files: `3`
- Max total weight size: `420 MB`
- Max total uncompressed zip size: `420 MB`
- Do not include hidden files, symlinks, binaries, or a nested top-level folder.

## run.py Contract

- Entry point is:
  - `python run.py --input /data/images --output /output/predictions.json`
- Input directory contains JPEG shelf images named like `img_00042.jpg`.
- Output must be a JSON array of objects with:
  - `image_id`
  - `category_id`
  - `bbox` in COCO `[x, y, w, h]`
  - `score` in `[0, 1]`

## Sandbox Constraints

- Python: `3.11`
- CPU: `4 vCPU`
- Memory: `8 GB`
- GPU: `NVIDIA L4 (24 GB VRAM)`
- CUDA: `12.4`
- Network: none
- Timeout: `300 seconds`

Use the sandbox package set as the compatibility target:
- `torch==2.6.0`
- `torchvision==0.21.0`
- `ultralytics==8.1.0`
- `onnxruntime-gpu==1.20.0`
- `timm==0.9.12`

For ONNX inference, use:
- `["CUDAExecutionProvider", "CPUExecutionProvider"]`

## Compatibility Rules

- Do not assume newer training-time package versions will load in the sandbox.
- `ultralytics 8.2+` checkpoints may fail on sandbox `8.1.0`.
  - Prefer ONNX export or train/package with `ultralytics==8.1.0`.
- `torch 2.7+` full-model saves may fail on sandbox `2.6.0`.
  - Prefer `state_dict` saves, not `torch.save(model)`.
- `timm 1.0+` weights may fail on sandbox `0.9.12`.
  - Prefer pinned `timm==0.9.12` or export to ONNX.
- ONNX opset must stay `<= 20`.
  - Prefer `opset_version=17`.

## Preferred Packaging Strategy

- Prefer an ONNX detector over raw Ultralytics `.pt` unless the checkpoint is known to be trained and loaded with sandbox `ultralytics==8.1.0`.
- Prefer classifier/custom-model checkpoints that are plain `state_dict` payloads with explicit model reconstruction in code.
- Avoid full-model pickle-style `.pt` files when a `state_dict` or `.safetensors` alternative exists.

## Security Restrictions

The security scanner blocks these imports:
- `os`
- `sys`
- `subprocess`
- `socket`
- `ctypes`
- `builtins`
- `importlib`
- `pickle`
- `marshal`
- `shelve`
- `shutil`
- `yaml`
- `requests`
- `urllib`
- `http.client`
- `multiprocessing`
- `threading`
- `signal`
- `gc`
- `code`
- `codeop`
- `pty`

The security scanner blocks these calls/patterns:
- `eval()`
- `exec()`
- `compile()`
- `__import__()`
- `getattr()` with dangerous names
- binaries, symlinks, and path traversal

Additional repo-local scanner rules to avoid:
- Do not use dynamic `getattr(...)` in submission code.
- Do not use `setattr(...)` or `delattr(...)`.
- Do not access dangerous dunder attributes such as:
  - `__class__`
  - `__bases__`
  - `__mro__`
  - `__subclasses__`
  - `__globals__`
  - `__code__`

Safe patterns:
- Use `pathlib` instead of `os`.
- Use `json` instead of `yaml`.
- Keep control flow explicit and static.
- Reconstruct models with direct class/layer references, not reflection.

## Working Rules For This Repo

- Before changing submission packaging, `run.py`, or model formats, check this file first.
- Before creating a submission zip, run the local submission checker.
- When possible, validate the actual packaged inference path locally, not just the training checkpoint.
- Treat scanner safety and sandbox compatibility as release blockers, not cleanup tasks.
