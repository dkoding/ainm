from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency for local convenience
    load_dotenv = None


ENV_FILE = Path(__file__).with_name(".env")
DEFAULT_AINM_BASE_URL = "https://api.ainm.no"
DEFAULT_OUTPUT_DIR = Path("artifacts")
DEFAULT_SUBMIT = False
DEFAULT_SIMULATE = False
DEFAULT_QUERIES_PER_SEED = 4
DEFAULT_VIEWPORT_SIZE = 15
DEFAULT_PREDICTION_FLOOR = 0.01
DEFAULT_OBSERVATION_PRIOR_STRENGTH = 2.0
DEFAULT_GCS_ARTIFACTS_PREFIX = "astar"
DEFAULT_HISTORY_CACHE_PREFIX = "history"


def load_local_env() -> None:
    if load_dotenv is not None and ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)


@dataclass(frozen=True)
class AstarSettings:
    access_token: str | None

    @classmethod
    def from_env(cls) -> "AstarSettings":
        load_local_env()
        return cls(
            access_token=os.getenv("AINM_ACCESS_TOKEN") or None,
        )
