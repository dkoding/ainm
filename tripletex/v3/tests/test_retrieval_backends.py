from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.contracts import IntentDocument
from app.llm.context_catalog import ContextCatalog
from app.llm.retrieval_backends import RetrievalQuery, RetrievalSelection, VertexRagRetrievalBackend
from app.raw.errors import RawExecutionError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, json: dict[str, object], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.response


class StaticRemoteBackend:
    configured = True

    def retrieve(self, query: RetrievalQuery) -> RetrievalSelection:
        return RetrievalSelection(
            backend="vertex_rag",
            flow_names=("project.create_for_customer",),
            command_names=("project.create",),
            raw_operation_ids=("Project_post",),
            notes=("retrieved from fake remote backend",),
        )


class FailingRemoteBackend:
    configured = True

    def retrieve(self, query: RetrievalQuery) -> RetrievalSelection:
        raise RawExecutionError(message="boom")


class RetrievalBackendTests(unittest.TestCase):
    def _intent(self, **overrides: object) -> IntentDocument:
        payload: dict[str, object] = {
            "contractVersion": "tripletex.intent.v1",
            "intentSummary": "test intent",
            "taskFamilies": [],
            "targetResources": [],
            "operations": [],
            "routeHints": {
                "flowNames": [],
                "commandNames": [],
                "operationIds": [],
                "technicalFlowFamilies": [],
                "domains": [],
                "subdomains": [],
                "selectorFamilies": [],
                "payloadFamilies": [],
            },
        }
        payload.update(overrides)
        return IntentDocument.model_validate(payload)

    def test_vertex_rag_backend_parses_document_names_from_context_response(self) -> None:
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "contexts": {
                        "contexts": [
                            {
                                "sourceDisplayName": "raw__TimesheetEntryTotalHours_getTotalHours.md",
                                "text": "doc_type: raw_operation\noperation_id: TimesheetEntryTotalHours_getTotalHours\n",
                            },
                            {
                                "sourceDisplayName": "command__project.create.md",
                                "text": "doc_type: command\ncommand_name: project.create\n",
                            },
                            {
                                "sourceDisplayName": "flow__project.create_for_customer.md",
                                "text": "doc_type: flow\nflow_name: project.create_for_customer\n",
                            },
                        ]
                    }
                },
            )
        )
        with patch.dict(
            os.environ,
            {
                "TRIPLETEX_VERTEX_RAG_CORPUS": "projects/demo/locations/europe-north1/ragCorpora/spec-corpus",
                "TRIPLETEX_VERTEX_RAG_TOP_K": "12",
                "TRIPLETEX_VERTEX_RAG_TIMEOUT_SECONDS": "9",
            },
            clear=False,
        ):
            backend = VertexRagRetrievalBackend()
            backend._session = session  # type: ignore[assignment]
            selection = backend.retrieve(
                RetrievalQuery(
                    prompt="Create a project",
                    text="Create a project for customer ACME AS",
                    tokens=frozenset({"create", "project", "customer"}),
                )
            )

        self.assertEqual(selection.raw_operation_ids, ("TimesheetEntryTotalHours_getTotalHours",))
        self.assertEqual(selection.command_names, ("project.create",))
        self.assertEqual(selection.flow_names, ("project.create_for_customer",))
        self.assertEqual(len(session.calls), 1)
        call = session.calls[0]
        self.assertIn("/v1/projects/demo/locations/europe-north1:retrieveContexts", call["url"])
        self.assertEqual(call["json"]["query"]["similarityTopK"], 12)  # type: ignore[index]
        self.assertEqual(call["timeout"], 9.0)

    def test_context_catalog_merges_remote_candidates_with_local_rerank(self) -> None:
        catalog = ContextCatalog(
            retrieval_backend_name="vertex_rag",
            remote_backend=StaticRemoteBackend(),
        )
        intent = self._intent(
            routeHints={
                "flowNames": ["project.create_for_customer"],
                "commandNames": ["project.create"],
                "operationIds": ["Project_post"],
                "technicalFlowFamilies": ["project.create"],
                "domains": ["project"],
                "subdomains": ["root"],
                "selectorFamilies": ["customer_selector", "employee_selector"],
                "payloadFamilies": [],
            },
            needsMutation=True,
            needsResolution=True,
        )

        context = catalog.build_slice(
            "Create a project for customer ACME AS with Jane Doe as project manager",
            intent=intent,
        )

        self.assertEqual(context["retrieval"]["backend"], "vertex_rag")
        self.assertEqual(context["apiContract"]["candidateFlowNames"][0], "project.create_for_customer")
        self.assertIn("Project_post", context["rawApiContract"]["candidateOperationIds"])
        self.assertIn("Project_post", context["rawApiContract"]["candidateOperationIds"])

    def test_context_catalog_falls_back_to_local_when_remote_retrieval_fails(self) -> None:
        catalog = ContextCatalog(
            retrieval_backend_name="vertex_rag",
            remote_backend=FailingRemoteBackend(),
        )
        intent = self._intent(
            routeHints={
                "flowNames": [],
                "commandNames": [],
                "operationIds": ["TimesheetEntryTotalHours_getTotalHours"],
                "technicalFlowFamilies": ["timesheet.entry.total_hours"],
                "domains": ["timesheet"],
                "subdomains": ["entry"],
                "selectorFamilies": [],
                "payloadFamilies": [],
            },
            needsResolution=True,
        )

        context = catalog.build_slice("How many hours did I work in February?", intent=intent)

        self.assertEqual(context["retrieval"]["backend"], "local")
        self.assertTrue(any("Vertex RAG retrieval failed" in warning for warning in context["retrieval"]["warnings"]))
        self.assertEqual(context["rawApiContract"]["candidateOperationIds"][0], "TimesheetEntryTotalHours_getTotalHours")


if __name__ == "__main__":
    unittest.main()
