from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Iterable

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import AuthorizedSession
import requests

from app.llm.retrieval_docs import parse_retrieval_document_ref, parse_retrieval_document_text
from app.raw.errors import RawExecutionError


logger = logging.getLogger("tripletex_retrieval")


@dataclass(frozen=True)
class RetrievalQuery:
    prompt: str
    text: str
    tokens: frozenset[str]
    attachment_count: int = 0
    attachment_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalSelection:
    backend: str
    flow_names: tuple[str, ...] = ()
    command_names: tuple[str, ...] = ()
    raw_operation_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _read_float_env(name: str, *, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _read_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


class VertexRagRetrievalBackend:
    def __init__(self, timeout: float = 10.0) -> None:
        self.rag_corpus = os.getenv("TRIPLETEX_VERTEX_RAG_CORPUS", "").strip()
        self.endpoint = (
            os.getenv("TRIPLETEX_VERTEX_RAG_ENDPOINT", "https://aiplatform.googleapis.com").strip()
            or "https://aiplatform.googleapis.com"
        )
        self.timeout = _read_float_env("TRIPLETEX_VERTEX_RAG_TIMEOUT_SECONDS", default=timeout)
        self.top_k = _read_int_env("TRIPLETEX_VERTEX_RAG_TOP_K", default=64)
        self._session: AuthorizedSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.rag_corpus)

    def retrieve(self, query: RetrievalQuery) -> RetrievalSelection:
        if not self.rag_corpus:
            raise RawExecutionError(message="TRIPLETEX_VERTEX_RAG_CORPUS is required for Vertex RAG retrieval.")
        parent = self._parent_resource()
        payload: dict[str, Any] = {
            "query": {
                "text": query.text,
                "similarityTopK": self.top_k,
            },
            "vertexRagStore": {
                "ragResources": [{"ragCorpus": self.rag_corpus}],
            },
        }
        url = f"{self.endpoint.rstrip('/')}/v1/{parent}:retrieveContexts"
        try:
            response = self._get_session().post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RawExecutionError(
                message="Vertex RAG retrieval request failed.",
                details={"errorType": exc.__class__.__name__, "message": str(exc)[:2000]},
            ) from exc
        if response.status_code >= 400:
            raise RawExecutionError(
                message=f"Vertex RAG retrieval returned HTTP {response.status_code}.",
                status_code=response.status_code,
                details={"body": response.text[:2000]},
            )
        data = response.json()
        contexts = data.get("contexts", {}).get("contexts", [])
        if not isinstance(contexts, list):
            raise RawExecutionError(
                message="Vertex RAG retrieval returned an unexpected response shape.",
                details={"body": data},
            )
        flow_names: list[str] = []
        command_names: list[str] = []
        raw_operation_ids: list[str] = []
        for item in contexts:
            identity = self._extract_identity(item)
            if identity is None:
                continue
            doc_type, canonical_name = identity
            if doc_type == "flow":
                flow_names.append(canonical_name)
            elif doc_type == "command":
                command_names.append(canonical_name)
            elif doc_type == "raw_operation":
                raw_operation_ids.append(canonical_name)
        warnings: list[str] = []
        if contexts and not (flow_names or command_names or raw_operation_ids):
            warnings.append("Vertex RAG returned contexts, but none of them could be mapped to known retrieval document ids.")
        return RetrievalSelection(
            backend="vertex_rag",
            flow_names=tuple(_ordered_unique(flow_names)),
            command_names=tuple(_ordered_unique(command_names)),
            raw_operation_ids=tuple(_ordered_unique(raw_operation_ids)),
            notes=(f"retrieved {len(contexts)} context chunks from Vertex RAG",),
            warnings=tuple(warnings),
        )

    def _parent_resource(self) -> str:
        parts = self.rag_corpus.split("/")
        if len(parts) != 6 or parts[0] != "projects" or parts[2] != "locations" or parts[4] != "ragCorpora":
            raise RawExecutionError(
                message="TRIPLETEX_VERTEX_RAG_CORPUS must use the format projects/{project}/locations/{location}/ragCorpora/{corpus}."
            )
        return "/".join(parts[:4])

    def _get_session(self) -> AuthorizedSession:
        if self._session is not None:
            return self._session
        try:
            credentials, _detected_project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        except DefaultCredentialsError as exc:
            raise RawExecutionError(
                message="Application Default Credentials are not configured for Vertex RAG retrieval."
            ) from exc
        self._session = AuthorizedSession(credentials)
        return self._session

    def _extract_identity(self, item: Any) -> tuple[str, str] | None:
        strings = list(_walk_strings(item))
        for value in strings:
            identity = parse_retrieval_document_ref(value)
            if identity is not None:
                return identity
        for value in strings:
            identity = parse_retrieval_document_text(value)
            if identity is not None:
                return identity
        return None


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
