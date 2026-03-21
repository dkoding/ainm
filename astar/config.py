from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency for local convenience
    load_dotenv = None


ASTAR_ROOT = Path(__file__).resolve().parent
ENV_FILE = ASTAR_ROOT / ".env"
DEFAULT_AINM_BASE_URL = "https://api.ainm.no"
DEFAULT_OUTPUT_DIR = ASTAR_ROOT / "artifacts"
DEFAULT_SUBMIT = False
DEFAULT_SIMULATE = False
DEFAULT_STAGED_SUBMIT = True
DEFAULT_QUERIES_PER_SEED = 4
DEFAULT_TOTAL_QUERIES = 50
DEFAULT_VIEWPORT_SIZE = 15
DEFAULT_PREDICTION_FLOOR = 0.02
DEFAULT_OBSERVATION_PRIOR_STRENGTH = 2.0
DEFAULT_HISTORY_PRIOR_STRENGTH = 4.0
DEFAULT_GCS_ARTIFACTS_PREFIX = "astar"
DEFAULT_HISTORY_CACHE_PREFIX = "history"
DEFAULT_NEIGHBORHOOD_RADIUS = 1
DEFAULT_SKLEARN_N_ESTIMATORS = 300
DEFAULT_SKLEARN_MIN_SAMPLES_LEAF = 5
DEFAULT_SKLEARN_RANDOM_STATE = 0
DEFAULT_SYNC_HISTORY = True


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
