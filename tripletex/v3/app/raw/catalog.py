from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.utils import APP_ROOT, load_json


RAW_CATALOG_PATH = APP_ROOT / "generated" / "operation_catalog.json"


class RawCatalog:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.operations: dict[str, dict[str, Any]] = payload["operations"]

    def get(self, operation_id: str) -> dict[str, Any]:
        try:
            return self.operations[operation_id]
        except KeyError as exc:
            raise KeyError(f"Unknown raw operationId: {operation_id}") from exc

    def has(self, operation_id: str) -> bool:
        return operation_id in self.operations

    @property
    def count(self) -> int:
        return self.payload["operationCount"]


@lru_cache(maxsize=1)
def load_raw_catalog(path: Path = RAW_CATALOG_PATH) -> RawCatalog:
    return RawCatalog(load_json(path))
