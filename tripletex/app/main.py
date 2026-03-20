from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from .client import TripletexAPIError
from .execution import CommandExecutionError
from .models import SolveRequest, SolveResponse
from .openapi_registry import OpenAPIRegistryError
from .solver import PlannerError, SolveError, TripletexSolver, UnauthorizedError

app = FastAPI(title="Tripletex Agent")
solver = TripletexSolver()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/solve", response_model=SolveResponse)
def solve(request: SolveRequest, authorization: str | None = Header(default=None)) -> SolveResponse:
    try:
        return solver.solve(request, authorization)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PlannerError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except CommandExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OpenAPIRegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TripletexAPIError as exc:
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc
