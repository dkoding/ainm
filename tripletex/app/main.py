from __future__ import annotations

import logging
import os
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
REQUEST_TIMEOUT = float(os.getenv("TRIPLETEX_REQUEST_TIMEOUT", "30"))
EXPECTED_API_KEY = os.getenv("TRIPLETEX_API_KEY", "").strip()
WHO_AM_I_FIELDS = os.getenv("TRIPLETEX_WHOAMI_FIELDS", "").strip()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("tripletex_scaffold")

app = FastAPI(title="Tripletex Scaffold")


class SolveFile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)


class TripletexCredentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    base_url: str = Field(min_length=1)
    session_token: str = Field(min_length=1)


class SolveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str = Field(min_length=1)
    files: list[SolveFile] = Field(default_factory=list)
    tripletex_credentials: TripletexCredentials


class SolveResponse(BaseModel):
    status: str = "completed"


@app.get("/", include_in_schema=False)
def root() -> dict[str, Any]:
    return {
        "service": "tripletex-scaffold",
        "status": "ok",
        "endpoints": {
            "health": "/health",
            "solve": "/solve",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/solve", response_model=SolveResponse)
def solve(request: SolveRequest, authorization: str | None = Header(default=None)) -> SolveResponse:
    _require_api_key(authorization)
    _probe_tripletex(request.tripletex_credentials)
    logger.info(
        "solve.completed prompt_chars=%s files=%s base_url=%s",
        len(request.prompt),
        len(request.files),
        _redact_base_url(request.tripletex_credentials.base_url),
    )
    return SolveResponse()


def _require_api_key(authorization: str | None) -> None:
    if not EXPECTED_API_KEY:
        return
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != EXPECTED_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")


def _probe_tripletex(credentials: TripletexCredentials) -> None:
    base_url = credentials.base_url.rstrip("/")
    url = f"{base_url}/token/session/>whoAmI"
    try:
        params = {"fields": WHO_AM_I_FIELDS} if WHO_AM_I_FIELDS else None
        response = requests.get(
            url,
            auth=("0", credentials.session_token),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.exception("tripletex.connectivity_error base_url=%s", _redact_base_url(base_url))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach the Tripletex proxy.",
        ) from exc

    if response.status_code >= 400:
        logger.warning(
            "tripletex.error status=%s base_url=%s body=%r",
            response.status_code,
            _redact_base_url(base_url),
            response.text[:1000],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Tripletex proxy rejected the credentials or request.",
                "tripletex_status_code": response.status_code,
                "tripletex_body": response.text[:1000],
            },
        )

    logger.info("tripletex.probe_ok base_url=%s", _redact_base_url(base_url))


def _redact_base_url(base_url: str) -> str:
    if "://" not in base_url:
        return base_url[:120]
    scheme, rest = base_url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}"
