from __future__ import annotations

import logging
import os
from fastapi import FastAPI, Header, HTTPException, status
from app.contracts import SolveRequest, SolveResponse
from app.raw.errors import RawExecutionError
from app.solver import SolveService
from app.wrapper import load_wrapper_catalog


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
EXPECTED_API_KEY = os.getenv("TRIPLETEX_API_KEY", "").strip()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("tripletex_app")

app = FastAPI(title="Tripletex Solver")
solve_service = SolveService()
wrapper_catalog = load_wrapper_catalog()


@app.get("/", include_in_schema=False)
def root() -> dict[str, object]:
    return {
        "service": "tripletex-solver",
        "status": "ok",
        "endpoints": {
            "health": "/health",
            "solve": "/solve",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/catalog/commands")
def catalog_commands() -> dict[str, object]:
    return {
        "count": wrapper_catalog.command_count,
        "commands": wrapper_catalog.list_commands(),
    }


@app.get("/catalog/flows")
def catalog_flows() -> dict[str, object]:
    return {
        "count": wrapper_catalog.flow_count,
        "flows": wrapper_catalog.list_flows(),
    }


@app.post("/solve", response_model=SolveResponse)
def solve(request: SolveRequest, authorization: str | None = Header(default=None)) -> SolveResponse:
    _require_api_key(authorization)
    try:
        solve_service.execute(request)
    except RawExecutionError as exc:
        logger.warning("solve.failed message=%s details=%s", exc.message, exc.details)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": exc.message, "details": exc.details},
        ) from exc
    logger.info("solve.completed prompt_chars=%s files=%s", len(request.prompt), len(request.files))
    return SolveResponse()


def _require_api_key(authorization: str | None) -> None:
    if not EXPECTED_API_KEY:
        return
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != EXPECTED_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")
