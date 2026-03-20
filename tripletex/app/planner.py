from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


SYSTEM_PROMPT = """You are an agent that controls the Tripletex v2 REST API.

You get one accounting task plus the result of prior API calls.
Return JSON only. No markdown fences.

Allowed response shapes:
1. Take one API step:
{
  "kind": "action",
  "reason": "short explanation",
  "action": {
    "method": "GET | POST | PUT | DELETE",
    "path": "/employee",
    "params": {"fields": "id,name"},
    "json": {"name": "Acme AS"}
  }
}

2. Finish:
{
  "kind": "finish",
  "reason": "short explanation"
}

Rules:
- Use only the Tripletex proxy base_url already configured by the caller.
- Prefer exact, efficient API calls. Avoid unnecessary retries.
- If you need an existing entity, search before creating duplicates.
- When the task is complete, return kind=finish.
- Never invent endpoints outside standard Tripletex v2 paths.
- You may inspect saved attachments by their local file path, but this scaffold only gives you metadata and file locations.
"""


class PlannerError(RuntimeError):
    pass


@dataclass
class PlannerStep:
    kind: str
    reason: str
    method: str | None = None
    path: str | None = None
    params: dict[str, Any] | None = None
    json_body: Any | None = None


class BasePlanner:
    def next_step(
        self,
        *,
        task_prompt: str,
        attachments: list[dict[str, Any]],
        history: list[dict[str, Any]],
        remaining_steps: int,
    ) -> PlannerStep:
        raise NotImplementedError


class NoopPlanner(BasePlanner):
    def __init__(self, allow_noop: bool):
        self.allow_noop = allow_noop

    def next_step(
        self,
        *,
        task_prompt: str,
        attachments: list[dict[str, Any]],
        history: list[dict[str, Any]],
        remaining_steps: int,
    ) -> PlannerStep:
        if self.allow_noop:
            return PlannerStep(kind="finish", reason="NOOP mode enabled for transport testing.")
        raise PlannerError(
            "No planner configured. Set GOOGLE_CLOUD_PROJECT for Vertex AI or TRIPLETEX_ALLOW_NOOP=true for wiring tests."
        )


class VertexAIPlanner(BasePlanner):
    def __init__(self, project_id: str, location: str, model_name: str):
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
        except ImportError as exc:
            raise PlannerError("google-cloud-aiplatform is required for Vertex AI planning.") from exc

        vertexai.init(project=project_id, location=location)
        self.model = GenerativeModel(model_name)

    def next_step(
        self,
        *,
        task_prompt: str,
        attachments: list[dict[str, Any]],
        history: list[dict[str, Any]],
        remaining_steps: int,
    ) -> PlannerStep:
        payload = {
            "task_prompt": task_prompt,
            "attachments": attachments,
            "history": history[-6:],
            "remaining_steps": remaining_steps,
            "common_endpoints": [
                "/employee",
                "/customer",
                "/product",
                "/invoice",
                "/order",
                "/travelExpense",
                "/project",
                "/department",
                "/ledger/account",
                "/ledger/posting",
                "/ledger/voucher",
            ],
        }
        prompt = f"{SYSTEM_PROMPT}\n\nContext JSON:\n{json.dumps(payload, ensure_ascii=False)}"
        response = self.model.generate_content(prompt)
        text = getattr(response, "text", "") or ""
        data = _extract_json(text)
        kind = data.get("kind")
        reason = str(data.get("reason", "")).strip() or "No reason provided."

        if kind == "finish":
            return PlannerStep(kind="finish", reason=reason)

        if kind != "action":
            raise PlannerError(f"Planner returned unsupported kind: {kind!r}")

        action = data.get("action") or {}
        method = str(action.get("method", "")).upper()
        path = str(action.get("path", "")).strip()
        if method not in {"GET", "POST", "PUT", "DELETE"}:
            raise PlannerError(f"Planner returned unsupported method: {method!r}")
        if not path.startswith("/"):
            raise PlannerError(f"Planner returned invalid path: {path!r}")

        return PlannerStep(
            kind="action",
            reason=reason,
            method=method,
            path=path,
            params=action.get("params") or None,
            json_body=action.get("json"),
        )


def build_planner(*, allow_noop: bool) -> BasePlanner:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project_id:
        return NoopPlanner(allow_noop=allow_noop)
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "europe-north1").strip()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
    return VertexAIPlanner(project_id=project_id, location=location, model_name=model_name)


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.S)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        object_match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if object_match:
            cleaned = object_match.group(0)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise PlannerError(f"Planner returned invalid JSON: {text!r}") from exc
    if not isinstance(parsed, dict):
        raise PlannerError("Planner JSON response must be an object.")
    return parsed
