from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency for local convenience
    load_dotenv = None


ENV_FILE = Path(__file__).with_name(".env")


def load_local_env() -> None:
    if load_dotenv is not None and ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value)


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return float(raw_value)


@dataclass(frozen=True)
class AstarSettings:
    access_token: str | None
    base_url: str
    round_id: str | None
    output_dir: Path
    submit: bool
    simulate: bool
    queries_per_seed: int
    viewport_size: int
    prediction_floor: float
    observation_prior_strength: float
    gcs_artifacts_bucket: str | None
    gcs_artifacts_prefix: str
    google_cloud_project: str | None
    google_cloud_location: str
    cloud_run_job_name: str
    cloud_run_region: str
    cloud_run_job_cpu: str
    cloud_run_job_memory: str
    cloud_run_job_task_timeout: str
    cloud_run_service_account: str | None
    astar_token_secret_name: str | None

    @classmethod
    def from_env(cls) -> "AstarSettings":
        load_local_env()
        return cls(
            access_token=os.getenv("AINM_ACCESS_TOKEN") or None,
            base_url=os.getenv("AINM_BASE_URL", "https://api.ainm.no"),
            round_id=os.getenv("ASTAR_ROUND_ID") or None,
            output_dir=Path(os.getenv("ASTAR_OUTPUT_DIR", "artifacts")),
            submit=_env_bool("ASTAR_SUBMIT", False),
            simulate=_env_bool("ASTAR_SIMULATE", False),
            queries_per_seed=_env_int("ASTAR_QUERIES_PER_SEED", 4),
            viewport_size=_env_int("ASTAR_VIEWPORT_SIZE", 15),
            prediction_floor=_env_float("ASTAR_PREDICTION_FLOOR", 0.01),
            observation_prior_strength=_env_float("ASTAR_OBSERVATION_PRIOR_STRENGTH", 2.0),
            gcs_artifacts_bucket=os.getenv("GCS_ARTIFACTS_BUCKET") or None,
            gcs_artifacts_prefix=os.getenv("GCS_ARTIFACTS_PREFIX", "astar"),
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "europe-north1"),
            cloud_run_job_name=os.getenv("CLOUD_RUN_JOB_NAME", "astar-round-worker"),
            cloud_run_region=os.getenv("CLOUD_RUN_REGION", "europe-north1"),
            cloud_run_job_cpu=os.getenv("CLOUD_RUN_JOB_CPU", "1"),
            cloud_run_job_memory=os.getenv("CLOUD_RUN_JOB_MEMORY", "1Gi"),
            cloud_run_job_task_timeout=os.getenv("CLOUD_RUN_JOB_TASK_TIMEOUT", "900s"),
            cloud_run_service_account=os.getenv("CLOUD_RUN_SERVICE_ACCOUNT") or None,
            astar_token_secret_name=os.getenv("ASTAR_TOKEN_SECRET_NAME") or None,
        )
