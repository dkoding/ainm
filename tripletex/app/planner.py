from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from .openapi_registry import TripletexOpenAPIRegistry
from .tasking import AttachmentContext, PlannerDecision, TaskAnalysis

logger = logging.getLogger(__name__)


ANALYSIS_PROMPT = """You are preparing a deterministic Tripletex API execution.

Return JSON only. No markdown fences.

Produce exactly one JSON object with this shape:
{
  "objective": "short description of desired end state",
  "task_family": "resource.operation style label such as customer.create",
  "operation": "create | update | delete | invoice | register_payment | correct | reverse | search | other",
  "target_resource": "employee | customer | product | order | invoice | travelExpense | project | department | ledger | other",
  "detected_language": "best guess language name or code",
  "search_hints": {"key": "value"},
  "payload_fields": {"key": "value"},
  "attachment_required": true,
  "ambiguity_notes": ["short notes"],
  "risk_level": "low | medium | high",
  "completion_signals": ["facts that indicate the task is complete"],
  "notes": ["extra implementation notes"]
}

Rules:
- infer the likely Tripletex workflow family from the prompt and attachments
- keep search_hints limited to values useful for API lookups
- keep payload_fields limited to values likely needed for creation or update
- mark risk_level=high for destructive or ambiguous tasks
- do not invent facts that are not supported by the prompt or attachments
"""

EXECUTION_PROMPT = """You are a deterministic Tripletex v2 API planner.

Return JSON only. No markdown fences.

Allowed response shapes:
1. Take one API step:
{
  "kind": "action",
  "reason": "short explanation",
  "action": {
    "method": "GET | POST | PUT | DELETE",
    "path": "/customer",
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
- use only standard Tripletex v2 paths
- the action.path must match an actual OpenAPI path template, including prefixes like /ledger/ when required
- do not shorten or rename paths; for example use /ledger/vatType, not /vatType
- prefer paths listed in openapi_endpoint_hints
- prefer exact searches before create or update if duplicates are possible
- keep API calls efficient and minimal
- reuse earlier responses instead of repeating searches
- do not finish until the intended state change is complete
- if a request failed, use the error payload to repair the next step instead of guessing broadly
"""


class PlannerError(RuntimeError):
    pass


class BasePlanner:
    def analyze_task(
        self,
        *,
        task_prompt: str,
        attachments: list[AttachmentContext],
    ) -> TaskAnalysis:
        raise NotImplementedError

    def next_step(
        self,
        *,
        task_analysis: TaskAnalysis,
        attachments: list[AttachmentContext],
        history: list[dict[str, Any]],
        remaining_steps: int,
    ) -> PlannerDecision:
        raise NotImplementedError


class NoopPlanner(BasePlanner):
    def __init__(self, allow_noop: bool):
        self.allow_noop = allow_noop

    def analyze_task(
        self,
        *,
        task_prompt: str,
        attachments: list[AttachmentContext],
    ) -> TaskAnalysis:
        if not self.allow_noop:
            raise PlannerError(
                "No planner configured. Set GOOGLE_CLOUD_PROJECT for Vertex AI or TRIPLETEX_ALLOW_NOOP=true for wiring tests."
            )
        return TaskAnalysis(
            objective=task_prompt.strip(),
            task_family="noop.finish",
            operation="other",
            target_resource="other",
            detected_language="unknown",
            attachment_required=bool(attachments),
            notes=["NOOP mode enabled for wiring tests."],
        )

    def next_step(
        self,
        *,
        task_analysis: TaskAnalysis,
        attachments: list[AttachmentContext],
        history: list[dict[str, Any]],
        remaining_steps: int,
    ) -> PlannerDecision:
        if self.allow_noop:
            return PlannerDecision(kind="finish", reason="NOOP mode enabled for transport testing.")
        raise PlannerError("NOOP planner cannot run when TRIPLETEX_ALLOW_NOOP is false.")


class VertexAIPlanner(BasePlanner):
    def __init__(self, project_id: str, location: str, model_name: str):
        try:
            from google import genai
            from google.genai.types import HttpOptions, Part
        except ImportError as exc:
            raise PlannerError("google-genai is required for Vertex AI planning.") from exc

        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            http_options=HttpOptions(api_version="v1"),
        )
        self.part_type = Part
        self.model_name = model_name
        self.registry = TripletexOpenAPIRegistry.from_default_spec()

    def analyze_task(
        self,
        *,
        task_prompt: str,
        attachments: list[AttachmentContext],
    ) -> TaskAnalysis:
        started_at = time.monotonic()
        payload = {
            "task_prompt": task_prompt,
            "attachments": [attachment.model_dump(mode="json") for attachment in attachments],
            "openapi_endpoint_hints": self.registry.planner_hints(target_resource=None),
        }
        logger.info(
            "planner.analysis.start model=%s attachments=%s prompt_chars=%s endpoint_hints=%s",
            self.model_name,
            len(attachments),
            len(task_prompt),
            len(payload["openapi_endpoint_hints"]),
        )
        response_text = self._generate_json(
            prompt=ANALYSIS_PROMPT,
            payload=payload,
            attachments=attachments,
        )
        logger.info(
            "planner.analysis.response elapsed_ms=%s response_chars=%s preview=%r",
            round((time.monotonic() - started_at) * 1000, 1),
            len(response_text),
            response_text[:400],
        )
        try:
            return TaskAnalysis.model_validate(_extract_json(response_text))
        except Exception as exc:
            logger.exception("planner.analysis.parse_failed response_preview=%r", response_text[:1200])
            raise PlannerError(f"Failed to parse task analysis: {response_text!r}") from exc

    def next_step(
        self,
        *,
        task_analysis: TaskAnalysis,
        attachments: list[AttachmentContext],
        history: list[dict[str, Any]],
        remaining_steps: int,
    ) -> PlannerDecision:
        started_at = time.monotonic()
        payload = {
            "task_analysis": task_analysis.model_dump(mode="json"),
            "attachments": [attachment.model_dump(mode="json") for attachment in attachments],
            "history": history[-6:],
            "remaining_steps": remaining_steps,
            "openapi_endpoint_hints": self.registry.planner_hints(target_resource=task_analysis.target_resource),
        }
        logger.info(
            "planner.step.start model=%s task_family=%s remaining_steps=%s history_entries=%s endpoint_hints=%s",
            self.model_name,
            task_analysis.task_family,
            remaining_steps,
            len(history),
            len(payload["openapi_endpoint_hints"]),
        )
        response_text = self._generate_json(
            prompt=EXECUTION_PROMPT,
            payload=payload,
            attachments=[],
        )
        logger.info(
            "planner.step.response elapsed_ms=%s response_chars=%s preview=%r",
            round((time.monotonic() - started_at) * 1000, 1),
            len(response_text),
            response_text[:400],
        )
        try:
            decision = PlannerDecision.model_validate(_extract_json(response_text))
        except Exception as exc:
            logger.exception("planner.step.parse_failed response_preview=%r", response_text[:1200])
            raise PlannerError(f"Failed to parse planner decision: {response_text!r}") from exc

        if decision.kind == "action":
            action = decision.action
            if action is None:
                raise PlannerError("Planner returned kind=action without an action payload.")
            if not action.path.startswith("/"):
                raise PlannerError(f"Planner returned invalid path: {action.path!r}")
            logger.info(
                "planner.step.action method=%s path=%s params=%s",
                action.method,
                action.path,
                sorted((action.params or {}).keys()),
            )
            if self.registry.match_operation(method=action.method, path=action.path) is None:
                logger.warning(
                    "planner.step.action_not_in_spec method=%s path=%s target_resource=%s",
                    action.method,
                    action.path,
                    task_analysis.target_resource,
                )
        else:
            logger.info("planner.step.finish reason=%r", decision.reason[:240])

        return decision

    def _generate_json(
        self,
        *,
        prompt: str,
        payload: dict[str, Any],
        attachments: list[AttachmentContext],
    ) -> str:
        contents: list[Any] = [f"{prompt}\n\nContext JSON:\n{json.dumps(payload, ensure_ascii=False)}"]
        for attachment in attachments:
            binary_part = self._attachment_part(attachment)
            if binary_part is not None:
                contents.append(
                    f"Attachment binary follows. Metadata JSON:\n{json.dumps(attachment.model_dump(mode='json'), ensure_ascii=False)}"
                )
                contents.append(binary_part)

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config={
                "temperature": 0,
                "response_mime_type": "application/json",
            },
        )
        return getattr(response, "text", "") or ""

    def _attachment_part(self, attachment: AttachmentContext) -> Any | None:
        if attachment.media_kind not in {"image", "pdf"}:
            return None
        if attachment.size_bytes > 15 * 1024 * 1024:
            return None
        try:
            raw_bytes = _read_bytes(attachment.path)
        except OSError:
            return None
        return self.part_type.from_bytes(data=raw_bytes, mime_type=attachment.mime_type)


def build_planner(*, allow_noop: bool) -> BasePlanner:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project_id:
        return NoopPlanner(allow_noop=allow_noop)
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "europe-north1").strip()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro").strip()
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

def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()
