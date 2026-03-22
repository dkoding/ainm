from __future__ import annotations

from typing import Any

from app.benchmark.models import BenchmarkRouteContract, FamilyExtraction, NormalizedRequest, TaskFamilyManifest
from app.contracts import LLMBridgeDocument
from app.llm.response_validator import ResponseValidator


class BenchmarkBridgeBuilder:
    def __init__(self, validator: ResponseValidator | None = None) -> None:
        self.validator = validator or ResponseValidator()

    def build(
        self,
        *,
        manifest: TaskFamilyManifest,
        route_contract: BenchmarkRouteContract,
        extraction: FamilyExtraction,
        request: NormalizedRequest,
        request_id: str,
        current_date: str,
        timezone: str,
    ) -> LLMBridgeDocument:
        step_id = "benchmark_step_1"
        payload = {
            "contractVersion": "tripletex.llm_bridge.v1",
            "requestContext": {
                "requestId": request_id,
                "currentDate": current_date,
                "timezone": timezone,
                "promptCharCount": len(request.prompt),
                "attachmentCount": len(request.attachments),
                "hasTripletexCredentials": True,
            },
            "language": {
                "promptOriginal": request.prompt,
                "promptCanonical": request.prompt,
            },
            "understanding": {
                "objective": manifest.summary,
                "intentSummary": manifest.summary,
                "taskFamilies": [manifest.family_id],
                "targetResources": [manifest.family_id.split(".", 1)[0]],
                "operations": [route_contract.route_name],
                "attachmentRequired": manifest.requires_attachment,
            },
            "sources": {
                "prompt": request.prompt,
                "attachments": [self._attachment_source(attachment) for attachment in request.attachments],
            },
            "richData": {
                "scalarFacts": dict(extraction.inputs),
            },
            "flatBridge": {
                "primaryEntityRefs": {},
                "fieldBag": {},
                "byEntityId": {},
                "flowArguments": {},
                "commandArguments": {},
            },
            "executionPlan": {
                "selectedFlows": [],
                "selectedCommands": [],
                "fallbackRawCommands": [],
                "stepOrder": [step_id],
            },
            "validation": {
                "isExecutable": True,
                "blockingIssues": [],
                "warnings": list(extraction.warnings),
            },
            "completion": {
                "completionSignals": [manifest.summary],
                "postconditions": [manifest.summary],
            },
        }
        step_inputs = dict(extraction.inputs)
        if route_contract.route_kind == "flow":
            payload["executionPlan"]["selectedFlows"] = [
                {
                    "stepId": step_id,
                    "flowName": route_contract.route_name,
                    "flowType": "business_flow",
                    "why": manifest.summary,
                    "inputs": step_inputs,
                }
            ]
        elif route_contract.route_kind == "command":
            payload["executionPlan"]["selectedCommands"] = [
                {
                    "stepId": step_id,
                    "commandName": route_contract.route_name,
                    "commandType": "friendly_alias",
                    "why": manifest.summary,
                    "inputs": step_inputs,
                }
            ]
        else:
            payload["executionPlan"]["fallbackRawCommands"] = [
                {
                    "stepId": step_id,
                    "commandType": "raw_operation",
                    "operationId": route_contract.route_name,
                    "why": manifest.summary,
                    "inputs": step_inputs,
                }
            ]
        return self.validator.validate(payload)

    def _attachment_source(self, attachment: Any) -> dict[str, Any]:
        return {
            "attachmentId": attachment.attachment_id,
            "filename": attachment.filename,
            "mimeType": attachment.mime_type,
            "documentType": attachment.document_type,
            "summary": attachment.summary,
            "factHints": list(attachment.fact_hints),
            "structuredFacts": attachment.structured_facts,
            "warnings": list(attachment.warnings),
        }
