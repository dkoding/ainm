from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request

from .client import TripletexAPIError
from .execution import CommandExecutionError
from .logging_utils import configure_logging, reset_request_id, set_request_id
from .models import SolveRequest, SolveResponse
from .openapi_registry import OpenAPIRegistryError
from .solver import PlannerError, SolveError, TripletexSolver, UnauthorizedError

configure_logging()

app = FastAPI(title="Tripletex Agent")
solver = TripletexSolver()
logger = logging.getLogger(__name__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = set_request_id(request_id)
    started_at = time.monotonic()
    logger.info(
        "http.request.start method=%s path=%s client=%s user_agent=%r",
        request.method,
        request.url.path,
        request.client.host if request.client else "-",
        request.headers.get("user-agent", "-"),
    )
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
        logger.exception("http.request.exception path=%s elapsed_ms=%s", request.url.path, elapsed_ms)
        reset_request_id(token)
        raise

    elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
    response.headers["x-request-id"] = request_id
    logger.info(
        "http.request.end method=%s path=%s status=%s elapsed_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    reset_request_id(token)
    return response


def _handle_solve(request: SolveRequest, authorization: str | None) -> SolveResponse:
    logger.info("solve.request payload=%s", _summarize_solve_request(request, authorization))
    try:
        return solver.solve(request, authorization)
    except UnauthorizedError as exc:
        logger.warning("Unauthorized /solve request: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PlannerError as exc:
        logger.exception("PlannerError while handling /solve")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except CommandExecutionError as exc:
        logger.exception("CommandExecutionError while handling /solve")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OpenAPIRegistryError as exc:
        logger.exception("OpenAPIRegistryError while handling /solve")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TripletexAPIError as exc:
        logger.exception("TripletexAPIError while handling /solve")
        raise HTTPException(
            status_code=502,
            detail={
                "error": str(exc),
                "status_code": exc.status_code,
                "method": exc.method,
                "path": exc.path,
                "payload": exc.payload,
            },
        ) from exc
    except SolveError as exc:
        logger.exception("SolveError while handling /solve")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/", response_model=SolveResponse, include_in_schema=False)
def solve_root(request: SolveRequest, authorization: str | None = Header(default=None)) -> SolveResponse:
    return _handle_solve(request, authorization)


@app.post("/solve", response_model=SolveResponse)
def solve(request: SolveRequest, authorization: str | None = Header(default=None)) -> SolveResponse:
    return _handle_solve(request, authorization)


def _summarize_solve_request(request: SolveRequest, authorization: str | None) -> dict[str, object]:
    prompt = request.prompt
    return {
        "prompt": prompt[:2000],
        "prompt_chars": len(prompt),
        "files": [
            {
                "filename": file.filename,
                "mime_type": file.mime_type,
                "content_base64_chars": len(file.content_base64),
            }
            for file in request.files
        ],
        "tripletex_credentials": {
            "base_url": _redact_base_url(request.tripletex_credentials.base_url),
            "session_token_chars": len(request.tripletex_credentials.session_token),
            "session_token_present": bool(request.tripletex_credentials.session_token),
        },
        "authorization_present": bool(authorization),
        "authorization_scheme": authorization.split(" ", 1)[0] if authorization else None,
    }


def _redact_base_url(base_url: str) -> str:
    if "://" not in base_url:
        return base_url[:120]
    scheme, rest = base_url.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}"
