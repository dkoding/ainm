from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from google.cloud import storage
except ImportError:  # pragma: no cover - optional dependency
    storage = None


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # pragma: no cover - defensive fallback
            pass
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class ArtifactStore:
    def __init__(self, root: str | Path, gcs_bucket: str | None = None, gcs_prefix: str = "astar"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.gcs_bucket = gcs_bucket
        self.gcs_prefix = gcs_prefix.strip("/")
        self._storage_client = None

    def write_json(self, relative_path: str | Path, payload: Any) -> Path:
        relative_path = Path(relative_path)
        output_path = self.root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
        if self.gcs_bucket:
            self._upload_json(output_path, relative_path)
        return output_path

    def _upload_json(self, local_path: Path, relative_path: Path) -> None:
        if storage is None:
            raise RuntimeError("google-cloud-storage is required when GCS_ARTIFACTS_BUCKET is configured.")
        if self._storage_client is None:
            self._storage_client = storage.Client()
        bucket = self._storage_client.bucket(self.gcs_bucket)
        cloud_path = "/".join(part for part in [self.gcs_prefix, relative_path.as_posix()] if part)
        blob = bucket.blob(cloud_path)
        blob.upload_from_filename(str(local_path), content_type="application/json")
