from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any

from app.contracts import IntentDocument
from app.llm.contract_utils import input_names, split_required_inputs
from app.llm.retrieval_backends import RetrievalQuery, RetrievalSelection, VertexRagRetrievalBackend
from app.raw import load_raw_catalog
from app.raw.errors import RawExecutionError
from app.wrapper import load_wrapper_catalog


logger = logging.getLogger("tripletex_context_catalog")


def _read_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _identifier_tokens(value: str) -> set[str]:
    cleaned = (
        value.lower()
        .replace("/", ".")
        .replace("-", ".")
        .replace(" ", ".")
        .replace(":", ".")
    )
    return {token for token in cleaned.split(".") if token}


def _ordered_unique(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


@dataclass(frozen=True)
class IntentSignals:
    intent_summary: str
    flow_names: frozenset[str]
    command_names: frozenset[str]
    operation_ids: frozenset[str]
    technical_flow_families: frozenset[str]
    domains: frozenset[str]
    subdomains: frozenset[str]
    selector_families: frozenset[str]
    payload_families: frozenset[str]
    task_families: frozenset[str]
    target_resources: frozenset[str]
    operations: frozenset[str]
    attachment_hints: tuple[str, ...]
    query_terms: tuple[str, ...]
    query_tokens: frozenset[str]
    needs_mutation: bool | None
    needs_resolution: bool | None
    attachment_relevant: bool | None


class ContextCatalog:
    def __init__(
        self,
        *,
        retrieval_backend_name: str | None = None,
        candidate_flow_limit: int | None = None,
        candidate_command_limit: int | None = None,
        candidate_raw_limit: int | None = None,
        query_term_limit: int | None = None,
        remote_backend: VertexRagRetrievalBackend | None = None,
    ) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()
        self.retrieval_backend_name = (
            retrieval_backend_name
            or os.getenv("TRIPLETEX_RETRIEVAL_BACKEND", "local").strip()
            or "local"
        ).lower()
        self.flow_limit = max(1, candidate_flow_limit or _read_int_env("TRIPLETEX_RETRIEVAL_FLOW_LIMIT", default=12))
        self.command_limit = max(1, candidate_command_limit or _read_int_env("TRIPLETEX_RETRIEVAL_COMMAND_LIMIT", default=40))
        self.raw_limit = max(1, candidate_raw_limit or _read_int_env("TRIPLETEX_RETRIEVAL_RAW_LIMIT", default=120))
        self.query_term_limit = max(1, query_term_limit or _read_int_env("TRIPLETEX_RETRIEVAL_QUERY_TERM_LIMIT", default=40))
        self.remote_backend = remote_backend or VertexRagRetrievalBackend()
        self.flow_to_commands = {
            name: tuple(flow.get("commandNames", []))
            for name, flow in self.wrapper_catalog.flows.items()
        }
        self.command_to_flows = {
            name: tuple(command.get("workflowMembership", []))
            for name, command in self.wrapper_catalog.commands.items()
        }
        operation_to_commands: dict[str, list[str]] = {}
        for name, command in self.wrapper_catalog.commands.items():
            operation_id = str(command.get("operationId", "")).strip()
            if not operation_id:
                continue
            operation_to_commands.setdefault(operation_id, []).append(name)
        self.operation_to_commands = {
            operation_id: tuple(sorted(command_names))
            for operation_id, command_names in operation_to_commands.items()
        }
        self.command_metadata = {
            name: self._build_command_metadata(name)
            for name in self.wrapper_catalog.commands
        }
        self.flow_metadata = {
            name: self._build_flow_metadata(name)
            for name in self.wrapper_catalog.flows
        }
        self.raw_metadata = {
            operation_id: self._build_raw_metadata(operation_id)
            for operation_id in self.raw_catalog.operations
        }

    def build_slice(
        self,
        prompt: str,
        evidence: list[dict[str, Any]] | None = None,
        *,
        intent: IntentDocument | None = None,
    ) -> dict[str, Any]:
        evidence = evidence or []
        signals = self._intent_signals(intent=intent, evidence=evidence, prompt=prompt)
        retrieval_query = self._build_query(prompt, signals=signals)
        local_flow_names = self._rank_flow_names(signals)
        local_command_names = self._rank_command_names(signals)
        local_raw_operation_ids = self._rank_raw_operation_ids(signals)
        local_flow_names, local_command_names, local_raw_operation_ids = self._expand_candidate_graph(
            local_flow_names=local_flow_names,
            local_command_names=local_command_names,
            local_raw_operation_ids=local_raw_operation_ids,
        )
        selection = self._select_candidates(
            retrieval_query,
            local_flow_names=local_flow_names,
            local_command_names=local_command_names,
            local_raw_operation_ids=local_raw_operation_ids,
        )
        flow_names = list(selection.flow_names)
        command_names = self._filter_shadowed_mutation_commands(
            command_names=list(selection.command_names),
            flow_names=flow_names,
            signals=signals,
        )
        raw_operation_ids = list(selection.raw_operation_ids)

        flows = [self.wrapper_catalog.get_flow(name) for name in flow_names if self.wrapper_catalog.has_flow(name)]
        commands = [
            self.wrapper_catalog.get_command(name)
            for name in command_names
            if self.wrapper_catalog.has_command(name)
        ]
        raw_operations = [
            self.raw_catalog.get(operation_id)
            for operation_id in raw_operation_ids
            if self.raw_catalog.has(operation_id)
        ]
        return {
            "retrieval": {
                "backend": selection.backend,
                "queryTerms": list(signals.query_terms)[: self.query_term_limit],
                "attachmentHints": list(signals.attachment_hints),
                "intentSummary": signals.intent_summary,
                "intentHints": {
                    "flowNames": sorted(signals.flow_names),
                    "commandNames": sorted(signals.command_names),
                    "operationIds": sorted(signals.operation_ids),
                    "technicalFlowFamilies": sorted(signals.technical_flow_families),
                    "domains": sorted(signals.domains),
                    "subdomains": sorted(signals.subdomains),
                    "selectorFamilies": sorted(signals.selector_families),
                    "payloadFamilies": sorted(signals.payload_families),
                    "taskFamilies": sorted(signals.task_families),
                    "targetResources": sorted(signals.target_resources),
                    "operations": sorted(signals.operations),
                    "needsMutation": signals.needs_mutation,
                    "needsResolution": signals.needs_resolution,
                    "attachmentRelevant": signals.attachment_relevant,
                },
                "candidateCounts": {
                    "flows": len(flows),
                    "commands": len(commands),
                    "rawOperations": len(raw_operations),
                },
                "notes": list(selection.notes),
                "warnings": list(selection.warnings),
            },
            "routingRules": {
                "priority": [
                    "business_flow",
                    "friendly_alias",
                    "raw_operation",
                ],
                "ruleText": "Choose a candidate business flow first when one fits, then a candidate friendly command, then exact raw operationId fallback.",
            },
            "intentContract": intent.model_dump(mode="json") if intent is not None else None,
            "apiContract": {
                "contractVersion": "tripletex.api_contract.v3",
                "authority": (
                    "This is the candidate contract pack for the current request. Only flow names in candidateFlowNames and command names in "
                    "candidateCommandNames are legal for this prompt. If a name is not listed exactly here, it is illegal."
                ),
                "candidateFlowNames": [item["flowName"] for item in flows],
                "candidateCommandNames": [item["commandName"] for item in commands],
                "candidateFlows": [self._flow_contract_pack(item) for item in flows],
                "candidateCommands": [self._command_contract_pack(item) for item in commands],
            },
            "rawApiContract": {
                "authority": "Only exact raw operationIds listed in candidateOperationIds are legal for this prompt.",
                "candidateOperationIds": [item["operationId"] for item in raw_operations],
                "technicalFlowFamilies": sorted(
                    {
                        family
                        for item in raw_operations
                        for family in item.get("technicalFlowFamilies", [])
                        if family
                    }
                ),
            },
            "policyCatalog": self._policy_catalog(flows, commands, raw_operations),
            "selectorFamilies": self._selector_families(flows, commands),
            "payloadFamilies": self._payload_families(flows, commands),
            "rawOperations": [self._raw_pack(item) for item in raw_operations],
        }

    def _build_query(self, prompt: str, *, signals: IntentSignals) -> RetrievalQuery:
        query_parts = []
        if signals.intent_summary:
            query_parts.append(signals.intent_summary)
        if signals.query_terms:
            query_parts.append("Route hints: " + ", ".join(signals.query_terms[: self.query_term_limit]))
        if signals.attachment_hints:
            query_parts.append("Attachment hints: " + "; ".join(signals.attachment_hints))
        query_text = "\n".join(part for part in query_parts if part) or prompt
        return RetrievalQuery(
            prompt=prompt,
            text=query_text,
            tokens=signals.query_tokens,
            attachment_count=len(signals.attachment_hints),
            attachment_hints=signals.attachment_hints,
        )

    def _attachment_hints(self, evidence: list[dict[str, Any]]) -> list[str]:
        hints: list[str] = []
        for attachment in evidence[:3]:
            filename = str(attachment.get("filename", "")).strip()
            if filename:
                hints.append(f"filename={filename}")
            document_type = str(attachment.get("documentType", "")).strip()
            if document_type:
                hints.append(f"document_type={document_type}")
            fact_summary = str(attachment.get("factSummary", "")).strip()
            if fact_summary:
                hints.append(fact_summary)
            for hint in attachment.get("extractedFactHints", [])[:4]:
                text = str(hint).strip()
                if text:
                    hints.append(text)
        return hints[:12]

    def _intent_signals(
        self,
        *,
        intent: IntentDocument | None,
        evidence: list[dict[str, Any]],
        prompt: str,
    ) -> IntentSignals:
        attachment_hints = tuple(self._attachment_hints(evidence))
        flow_names: list[str] = []
        command_names: list[str] = []
        operation_ids: list[str] = []
        technical_flow_families: list[str] = []
        domains: list[str] = []
        subdomains: list[str] = []
        selector_families: list[str] = []
        payload_families: list[str] = []
        task_families: list[str] = []
        target_resources: list[str] = []
        operations: list[str] = []
        needs_mutation: bool | None = None
        needs_resolution: bool | None = None
        attachment_relevant: bool | None = bool(evidence)
        intent_summary = prompt
        if intent is not None:
            intent_summary = str(intent.intentSummary or prompt).strip() or prompt
            flow_names.extend(intent.routeHints.flowNames)
            command_names.extend(intent.routeHints.commandNames)
            operation_ids.extend(intent.routeHints.operationIds)
            technical_flow_families.extend(intent.routeHints.technicalFlowFamilies)
            domains.extend(intent.routeHints.domains)
            subdomains.extend(intent.routeHints.subdomains)
            selector_families.extend(intent.routeHints.selectorFamilies)
            payload_families.extend(intent.routeHints.payloadFamilies)
            task_families.extend(intent.taskFamilies)
            target_resources.extend(intent.targetResources)
            operations.extend(intent.operations)
            needs_mutation = intent.needsMutation
            needs_resolution = intent.needsResolution
            attachment_relevant = intent.attachmentRelevant if intent.attachmentRelevant is not None else attachment_relevant
        self._merge_attachment_route_hints(
            evidence,
            flow_names=flow_names,
            command_names=command_names,
            operation_ids=operation_ids,
            domains=domains,
        )
        ordered_terms = _ordered_unique(
            [
                *flow_names,
                *command_names,
                *operation_ids,
                *technical_flow_families,
                *domains,
                *subdomains,
                *selector_families,
                *payload_families,
                *task_families,
                *target_resources,
                *operations,
            ]
        )
        query_tokens = set()
        for value in ordered_terms:
            query_tokens.add(value)
            query_tokens.update(_identifier_tokens(value))
        return IntentSignals(
            intent_summary=intent_summary,
            flow_names=frozenset(_ordered_unique(flow_names)),
            command_names=frozenset(_ordered_unique(command_names)),
            operation_ids=frozenset(_ordered_unique(operation_ids)),
            technical_flow_families=frozenset(_ordered_unique(technical_flow_families)),
            domains=frozenset(_ordered_unique(domains)),
            subdomains=frozenset(_ordered_unique(subdomains)),
            selector_families=frozenset(_ordered_unique(selector_families)),
            payload_families=frozenset(_ordered_unique(payload_families)),
            task_families=frozenset(_ordered_unique(task_families)),
            target_resources=frozenset(_ordered_unique(target_resources)),
            operations=frozenset(_ordered_unique(operations)),
            attachment_hints=attachment_hints,
            query_terms=tuple(ordered_terms),
            query_tokens=frozenset(query_tokens),
            needs_mutation=needs_mutation,
            needs_resolution=needs_resolution,
            attachment_relevant=attachment_relevant,
        )

    def _merge_attachment_route_hints(
        self,
        evidence: list[dict[str, Any]],
        *,
        flow_names: list[str],
        command_names: list[str],
        operation_ids: list[str],
        domains: list[str],
    ) -> None:
        for attachment in evidence:
            document_type = str(attachment.get("documentType", "")).strip()
            if document_type:
                domains.append(document_type)
            structured_facts = attachment.get("structuredFacts")
            if not isinstance(structured_facts, dict):
                continue
            for hint in structured_facts.get("routeHints", []) or []:
                route_name = str(hint).strip()
                if not route_name:
                    continue
                if self.wrapper_catalog.has_flow(route_name):
                    flow_names.append(route_name)
                elif self.wrapper_catalog.has_command(route_name):
                    command_names.append(route_name)
                elif self.raw_catalog.has(route_name):
                    operation_ids.append(route_name)

    def _select_candidates(
        self,
        retrieval_query: RetrievalQuery,
        *,
        local_flow_names: list[str],
        local_command_names: list[str],
        local_raw_operation_ids: list[str],
    ) -> RetrievalSelection:
        local_selection = RetrievalSelection(
            backend="local",
            flow_names=tuple(local_flow_names[: self.flow_limit]),
            command_names=tuple(local_command_names[: self.command_limit]),
            raw_operation_ids=tuple(local_raw_operation_ids[: self.raw_limit]),
            notes=("candidate context selected from local catalog retrieval",),
        )
        if self.retrieval_backend_name != "vertex_rag":
            return local_selection
        if not getattr(self.remote_backend, "configured", True):
            return RetrievalSelection(
                backend="local",
                flow_names=local_selection.flow_names,
                command_names=local_selection.command_names,
                raw_operation_ids=local_selection.raw_operation_ids,
                notes=local_selection.notes,
                warnings=("Vertex RAG retrieval was requested, but TRIPLETEX_VERTEX_RAG_CORPUS is not configured.",),
            )
        try:
            remote_selection = self.remote_backend.retrieve(retrieval_query)
        except (RawExecutionError, ValueError) as exc:
            logger.warning("vertex_rag_retrieval_failed error=%s", str(exc))
            return RetrievalSelection(
                backend="local",
                flow_names=local_selection.flow_names,
                command_names=local_selection.command_names,
                raw_operation_ids=local_selection.raw_operation_ids,
                notes=local_selection.notes,
                warnings=(f"Vertex RAG retrieval failed, so local retrieval was used instead: {str(exc)}",),
            )
        if not (
            remote_selection.flow_names
            or remote_selection.command_names
            or remote_selection.raw_operation_ids
        ):
            return RetrievalSelection(
                backend="local",
                flow_names=local_selection.flow_names,
                command_names=local_selection.command_names,
                raw_operation_ids=local_selection.raw_operation_ids,
                notes=local_selection.notes,
                warnings=tuple(remote_selection.warnings)
                + ("Vertex RAG retrieval returned no usable candidates, so local retrieval was used instead.",),
            )
        return RetrievalSelection(
            backend="vertex_rag",
            flow_names=tuple(
                self._merge_remote_candidates(
                    remote_selection.flow_names,
                    local_flow_names,
                    limit=self.flow_limit,
                )
            ),
            command_names=tuple(
                self._merge_remote_candidates(
                    remote_selection.command_names,
                    local_command_names,
                    limit=self.command_limit,
                )
            ),
            raw_operation_ids=tuple(
                self._merge_remote_candidates(
                    remote_selection.raw_operation_ids,
                    local_raw_operation_ids,
                    limit=self.raw_limit,
                )
            ),
            notes=remote_selection.notes + ("Vertex RAG candidates were reranked locally against generated catalogs.",),
            warnings=remote_selection.warnings,
        )

    def _expand_candidate_graph(
        self,
        *,
        local_flow_names: list[str],
        local_command_names: list[str],
        local_raw_operation_ids: list[str],
    ) -> tuple[list[str], list[str], list[str]]:
        expanded_flows = set(local_flow_names[: max(self.flow_limit * 3, 24)])
        expanded_commands = set(local_command_names[: max(self.command_limit * 2, 48)])
        expanded_raw = set(local_raw_operation_ids[: max(self.raw_limit * 2, 96)])

        for _ in range(2):
            for flow_name in list(expanded_flows):
                for command_name in self.flow_to_commands.get(flow_name, ()):
                    if not self.wrapper_catalog.has_command(command_name):
                        continue
                    expanded_commands.add(command_name)
                    operation_id = str(self.wrapper_catalog.get_command(command_name).get("operationId", "")).strip()
                    if operation_id and self.raw_catalog.has(operation_id):
                        expanded_raw.add(operation_id)
            for command_name in list(expanded_commands):
                for flow_name in self.command_to_flows.get(command_name, ()):
                    if self.wrapper_catalog.has_flow(flow_name):
                        expanded_flows.add(flow_name)
                if self.wrapper_catalog.has_command(command_name):
                    operation_id = str(self.wrapper_catalog.get_command(command_name).get("operationId", "")).strip()
                    if operation_id and self.raw_catalog.has(operation_id):
                        expanded_raw.add(operation_id)
            for operation_id in list(expanded_raw):
                for command_name in self.operation_to_commands.get(operation_id, ()):
                    if self.wrapper_catalog.has_command(command_name):
                        expanded_commands.add(command_name)

        return (
            self._sort_candidates(expanded_flows, ranked=local_flow_names),
            self._sort_candidates(expanded_commands, ranked=local_command_names),
            self._sort_candidates(expanded_raw, ranked=local_raw_operation_ids),
        )

    def _sort_candidates(self, candidates: set[str], *, ranked: list[str]) -> list[str]:
        rank_index = {name: index for index, name in enumerate(ranked)}
        return sorted(
            (name for name in candidates if name),
            key=lambda name: (rank_index.get(name, 10**6), name),
        )

    def _filter_shadowed_mutation_commands(
        self,
        *,
        command_names: list[str],
        flow_names: list[str],
        signals: IntentSignals,
    ) -> list[str]:
        flow_set = set(flow_names)
        filtered: list[str] = []
        for command_name in command_names:
            meta = self.wrapper_catalog.get_command(command_name)
            business_flows = [
                flow_name
                for flow_name in meta.get("workflowMembership", [])
                if isinstance(flow_name, str) and flow_name in flow_set
            ]
            if not business_flows or meta.get("safetyClass") not in {"mutation", "destructive", "state_change", "high_risk"}:
                filtered.append(command_name)
                continue
            if command_name in signals.command_names:
                filtered.append(command_name)
        return filtered

    def _merge_remote_candidates(
        self,
        remote_candidates: tuple[str, ...],
        local_candidates: list[str],
        *,
        limit: int,
    ) -> list[str]:
        local_index = {name: index for index, name in enumerate(local_candidates)}
        remote_unique = list(dict.fromkeys(name for name in remote_candidates if name))
        remote_unique.sort(key=lambda name: (local_index.get(name, 10**6), name))
        selected: list[str] = []
        seen: set[str] = set()
        for name in remote_unique:
            if name in seen:
                continue
            seen.add(name)
            selected.append(name)
            if len(selected) >= limit:
                return selected
        for name in local_candidates:
            if name in seen:
                continue
            seen.add(name)
            selected.append(name)
            if len(selected) >= limit:
                break
        return selected

    def _rank_flow_names(self, signals: IntentSignals) -> list[str]:
        scored: list[tuple[int, str]] = []
        for flow_name in self.wrapper_catalog.flows:
            score = self._flow_score(flow_name, signals)
            if score > 0:
                scored.append((score, flow_name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [name for _, name in scored]

    def _flow_score(self, flow_name: str, signals: IntentSignals) -> int:
        meta = self.flow_metadata[flow_name]
        score = 0
        score += self._exact_match_score(flow_name, signals.flow_names, weight=1200)
        score += self._overlap_score(meta["command_names"], signals.command_names, weight=240)
        score += self._overlap_score(meta["operation_ids"], signals.operation_ids, weight=220)
        score += self._overlap_score(meta["technical_flow_families"], signals.technical_flow_families, weight=180)
        score += self._overlap_score(meta["domains"], signals.domains, weight=120)
        score += self._overlap_score(meta["subdomains"], signals.subdomains, weight=90)
        score += self._overlap_score(meta["selector_families"], signals.selector_families, weight=70)
        score += self._overlap_score(meta["payload_families"], signals.payload_families, weight=70)
        score += self._overlap_score(meta["technical_flow_families"], signals.task_families, weight=50)
        score += self._overlap_score(meta["domains"], signals.target_resources, weight=35)
        score += self._overlap_score(meta["subdomains"], signals.operations, weight=30)
        if signals.needs_mutation is True and meta["mutation_capable"]:
            score += 25
        if signals.needs_resolution is True and meta["read_capable"]:
            score += 20
        if signals.attachment_relevant and meta["attachment_related"]:
            score += 30
        return score

    def _rank_command_names(self, signals: IntentSignals) -> list[str]:
        scored: list[tuple[int, str]] = []
        for command_name in self.wrapper_catalog.commands:
            score = self._command_score(command_name, signals)
            if score > 0:
                scored.append((score, command_name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [name for _, name in scored]

    def _command_score(self, command_name: str, signals: IntentSignals) -> int:
        meta = self.command_metadata[command_name]
        score = 0
        score += self._exact_match_score(command_name, signals.command_names, weight=1100)
        score += self._exact_match_score(meta["operation_id"], signals.operation_ids, weight=300)
        score += self._overlap_score(meta["workflow_membership"], signals.flow_names, weight=240)
        score += self._overlap_score(meta["technical_flow_families"], signals.technical_flow_families, weight=190)
        score += self._overlap_score(meta["domains"], signals.domains, weight=120)
        score += self._overlap_score(meta["subdomains"], signals.subdomains, weight=90)
        score += self._overlap_score(meta["selector_families"], signals.selector_families, weight=70)
        score += self._overlap_score(meta["payload_families"], signals.payload_families, weight=70)
        score += self._overlap_score(meta["technical_flow_families"], signals.task_families, weight=50)
        score += self._overlap_score(meta["domains"], signals.target_resources, weight=35)
        score += self._overlap_score(meta["subdomains"], signals.operations, weight=30)
        if signals.needs_mutation is True and meta["mutation_capable"]:
            score += 20
        if signals.needs_resolution is True and meta["read_capable"]:
            score += 16
        if signals.attachment_relevant and meta["attachment_related"]:
            score += 24
        return score

    def _rank_raw_operation_ids(self, signals: IntentSignals) -> list[str]:
        scored: list[tuple[int, str]] = []
        for operation_id in self.raw_catalog.operations:
            score = self._raw_operation_score(operation_id, signals)
            if score > 0:
                scored.append((score, operation_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked_ids = [operation_id for _, operation_id in scored]
        ranked_items = [self.raw_catalog.get(operation_id) for operation_id in ranked_ids]
        if not ranked_items:
            return []
        blended = self._blend_raw_operations(ranked_items, signals)
        return [item["operationId"] for item in blended]

    def _raw_operation_score(self, operation_id: str, signals: IntentSignals) -> int:
        meta = self.raw_metadata[operation_id]
        score = 0
        score += self._exact_match_score(operation_id, signals.operation_ids, weight=1000)
        score += self._overlap_score(meta["command_names"], signals.command_names, weight=240)
        score += self._overlap_score(meta["flow_names"], signals.flow_names, weight=240)
        score += self._overlap_score(meta["technical_flow_families"], signals.technical_flow_families, weight=180)
        score += self._overlap_score(meta["domains"], signals.domains, weight=120)
        score += self._overlap_score(meta["subdomains"], signals.subdomains, weight=90)
        score += self._overlap_score(meta["technical_flow_families"], signals.task_families, weight=50)
        score += self._overlap_score(meta["domains"], signals.target_resources, weight=35)
        score += self._overlap_score(meta["subdomains"], signals.operations, weight=30)
        if signals.needs_mutation is True and meta["mutation_capable"]:
            score += 20
        if signals.needs_resolution is True and meta["read_capable"]:
            score += 16
        if signals.attachment_relevant and meta["attachment_related"]:
            score += 24
        return score

    def _blend_raw_operations(self, ranked: list[dict[str, Any]], signals: IntentSignals) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(items: list[dict[str, Any]], limit: int) -> None:
            added = 0
            for item in items:
                operation_id = item["operationId"]
                if operation_id in seen:
                    continue
                seen.add(operation_id)
                selected.append(item)
                added += 1
                if added >= limit:
                    break

        for domain in sorted(signals.domains):
            add([item for item in ranked if self._matches_domain_hint(item, domain)], limit=8)
        add(ranked, limit=self.raw_limit * 3)
        return selected

    def _matches_domain_hint(self, item: dict[str, Any], domain: str) -> bool:
        if item.get("domain") == domain:
            return True
        if domain in item.get("technicalFlowFamilies", []):
            return True
        return False

    def _exact_match_score(self, value: str, hints: frozenset[str], *, weight: int) -> int:
        if not value:
            return 0
        return weight if value in hints else 0

    def _overlap_score(self, values: set[str], hints: frozenset[str], *, weight: int) -> int:
        if not values or not hints:
            return 0
        return len(values & hints) * weight

    def _build_command_metadata(self, command_name: str) -> dict[str, Any]:
        command = self.wrapper_catalog.get_command(command_name)
        operation_id = str(command.get("operationId", "")).strip()
        raw_meta = self.raw_catalog.get(operation_id) if operation_id and self.raw_catalog.has(operation_id) else {}
        selector_families: set[str] = set()
        payload_families: set[str] = set()
        selector_family = str(command.get("selectorFamily", "")).strip()
        if selector_family:
            selector_families.add(selector_family)
        for semantic in (command.get("inputSemantics") or {}).values():
            if not isinstance(semantic, dict):
                continue
            nested_selector = str(semantic.get("selectorFamily", "")).strip()
            if nested_selector:
                selector_families.add(nested_selector)
            payload_family = str(semantic.get("payloadFamily", "")).strip()
            if payload_family:
                payload_families.add(payload_family)
            item_family = str(semantic.get("itemFamily", "")).strip()
            if item_family:
                payload_families.add(item_family)
        technical_families = {
            str(command.get("technicalFlowFamily", "")).strip(),
            *[
                str(family).strip()
                for family in raw_meta.get("technicalFlowFamilies", [])
                if str(family).strip()
            ],
        }
        technical_families.discard("")
        domain = str(raw_meta.get("domain", "")).strip()
        subdomain = str(raw_meta.get("subdomain", "")).strip()
        safety_class = str(command.get("safetyClass", "")).strip()
        method = str(raw_meta.get("method", "")).upper()
        request_body_kind = str(raw_meta.get("requestBody", {}).get("kind", "")).strip()
        return {
            "command_name": command_name,
            "operation_id": operation_id,
            "workflow_membership": {
                str(flow_name).strip()
                for flow_name in command.get("workflowMembership", [])
                if str(flow_name).strip()
            },
            "technical_flow_families": technical_families,
            "selector_families": selector_families,
            "payload_families": payload_families,
            "domains": {domain} if domain else set(),
            "subdomains": {subdomain} if subdomain else set(),
            "mutation_capable": safety_class in {"mutation", "destructive", "state_change", "high_risk"} or method in {"POST", "PUT", "DELETE", "PATCH"},
            "read_capable": method == "GET" or safety_class == "read_only",
            "attachment_related": request_body_kind == "multipart" or "attachment" in selector_families or domain == "attachment",
        }

    def _build_flow_metadata(self, flow_name: str) -> dict[str, Any]:
        flow = self.wrapper_catalog.get_flow(flow_name)
        command_names = {
            command_name
            for command_name in flow.get("commandNames", [])
            if isinstance(command_name, str) and self.wrapper_catalog.has_command(command_name)
        }
        operation_ids = {
            self.command_metadata[command_name]["operation_id"]
            for command_name in command_names
            if self.command_metadata[command_name]["operation_id"]
        }
        selector_families: set[str] = set()
        payload_families: set[str] = set()
        for semantic in (flow.get("inputSemantics") or {}).values():
            if not isinstance(semantic, dict):
                continue
            selector_family = str(semantic.get("selectorFamily", "")).strip()
            if selector_family:
                selector_families.add(selector_family)
            payload_family = str(semantic.get("payloadFamily", "")).strip()
            if payload_family:
                payload_families.add(payload_family)
            item_family = str(semantic.get("itemFamily", "")).strip()
            if item_family:
                payload_families.add(item_family)
        selector_families.update(
            family
            for command_name in command_names
            for family in self.command_metadata[command_name]["selector_families"]
        )
        payload_families.update(
            family
            for command_name in command_names
            for family in self.command_metadata[command_name]["payload_families"]
        )
        return {
            "flow_name": flow_name,
            "command_names": command_names,
            "operation_ids": operation_ids,
            "technical_flow_families": {
                family
                for command_name in command_names
                for family in self.command_metadata[command_name]["technical_flow_families"]
            },
            "domains": {
                domain
                for command_name in command_names
                for domain in self.command_metadata[command_name]["domains"]
            },
            "subdomains": {
                subdomain
                for command_name in command_names
                for subdomain in self.command_metadata[command_name]["subdomains"]
            },
            "selector_families": selector_families,
            "payload_families": payload_families,
            "mutation_capable": any(self.command_metadata[command_name]["mutation_capable"] for command_name in command_names),
            "read_capable": any(self.command_metadata[command_name]["read_capable"] for command_name in command_names),
            "attachment_related": any(self.command_metadata[command_name]["attachment_related"] for command_name in command_names),
        }

    def _build_raw_metadata(self, operation_id: str) -> dict[str, Any]:
        operation = self.raw_catalog.get(operation_id)
        method = str(operation.get("method", "")).upper()
        domain = str(operation.get("domain", "")).strip()
        subdomain = str(operation.get("subdomain", "")).strip()
        request_body_kind = str(operation.get("requestBody", {}).get("kind", "")).strip()
        return {
            "operation_id": operation_id,
            "technical_flow_families": {
                str(family).strip()
                for family in operation.get("technicalFlowFamilies", [])
                if str(family).strip()
            },
            "domains": {domain} if domain else set(),
            "subdomains": {subdomain} if subdomain else set(),
            "command_names": set(self.operation_to_commands.get(operation_id, ())),
            "flow_names": {
                flow_name
                for command_name in self.operation_to_commands.get(operation_id, ())
                for flow_name in self.command_to_flows.get(command_name, ())
                if self.wrapper_catalog.has_flow(flow_name)
            },
            "mutation_capable": method in {"POST", "PUT", "DELETE", "PATCH"},
            "read_capable": method == "GET",
            "attachment_related": request_body_kind == "multipart" or domain == "attachment",
        }

    def _selector_families(self, flows: list[dict[str, Any]], commands: list[dict[str, Any]]) -> dict[str, Any]:
        names: set[str] = set()
        for item in [*flows, *commands]:
            selector_family = item.get("selectorFamily")
            if selector_family:
                names.add(selector_family)
            for semantics in (item.get("inputSemantics") or {}).values():
                if isinstance(semantics, dict) and semantics.get("selectorFamily"):
                    names.add(semantics["selectorFamily"])
        return {
            name: self.wrapper_catalog.selector_families[name]
            for name in sorted(names)
            if name in self.wrapper_catalog.selector_families
        }

    def _payload_families(self, flows: list[dict[str, Any]], commands: list[dict[str, Any]]) -> dict[str, Any]:
        names: set[str] = set()
        for item in [*flows, *commands]:
            for semantics in (item.get("inputSemantics") or {}).values():
                if isinstance(semantics, dict) and semantics.get("payloadFamily"):
                    names.add(semantics["payloadFamily"])
        return {
            name: self.wrapper_catalog.payload_families[name]
            for name in sorted(names)
            if name in self.wrapper_catalog.payload_families
        }

    def _policy_catalog(
        self,
        flows: list[dict[str, Any]],
        commands: list[dict[str, Any]],
        raw_operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        keys: set[str] = set()
        for item in commands:
            policy_key = item.get("conformancePolicyKey")
            if policy_key:
                keys.add(policy_key)
        for item in flows:
            keys.update(self._flow_policy_keys(item))
        for item in raw_operations:
            policy_key = item.get("conformancePolicyKey")
            if policy_key:
                keys.add(policy_key)
        return {
            key: self.wrapper_catalog.policies[key]
            for key in sorted(keys)
            if key in self.wrapper_catalog.policies
        }

    def _command_contract_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        body_fields = self._command_body_fields(item)
        legal_inputs = self._command_legal_inputs(item)
        required_inputs, optional_inputs = split_required_inputs(legal_inputs, item.get("inputSpec"))
        return {
            "commandName": item["commandName"],
            "operationId": item["operationId"],
            "purpose": item["purpose"],
            "wrapperInputs": input_names(item["inputs"]),
            "bodyFields": body_fields,
            "requiredInputs": required_inputs,
            "optionalInputs": optional_inputs,
            "allInputs": legal_inputs,
            "inputSpec": item.get("inputSpec"),
            "inputSemantics": item.get("inputSemantics", {}),
            "inputTypeHints": self._command_input_type_hints(item),
            "selectorFamily": item.get("selectorFamily"),
            "technicalFlowFamily": item["technicalFlowFamily"],
            "safetyClass": item["safetyClass"],
            "allowsBodyPassthrough": bool(item.get("allowsBodyPassthrough")),
            "conformancePolicyKey": item.get("conformancePolicyKey"),
        }

    def _flow_contract_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        legal_inputs = input_names(item["inputs"])
        required_inputs, optional_inputs = split_required_inputs(legal_inputs, item.get("inputSpec"))
        return {
            "flowName": item["flowName"],
            "useWhen": item["useWhen"],
            "requiredInputs": required_inputs,
            "optionalInputs": optional_inputs,
            "allInputs": legal_inputs,
            "inputSpec": item.get("inputSpec"),
            "inputSemantics": item.get("inputSemantics", {}),
            "commandNames": item["commandNames"],
            "policyKeys": self._flow_policy_keys(item),
        }

    def _command_body_fields(self, item: dict[str, Any]) -> list[str]:
        if not item.get("allowsBodyPassthrough"):
            return []
        raw_meta = self.raw_catalog.get(item["operationId"])
        body_schema = next(iter(raw_meta.get("requestBody", {}).get("content", {}).values()), {})
        return sorted(
            name
            for name, value in body_schema.get("properties", {}).items()
            if not value.get("readOnly")
        )

    def _command_legal_inputs(self, item: dict[str, Any]) -> list[str]:
        legal_inputs = list(input_names(item["inputs"]))
        if item.get("allowsBodyPassthrough"):
            legal_inputs.extend(["body", "payload"])
            legal_inputs.extend(self._command_body_fields(item))
        return sorted(dict.fromkeys(name for name in legal_inputs if name))

    def _raw_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        body_schema = next(iter(item.get("requestBody", {}).get("content", {}).values()), {})
        body_fields = sorted(
            name
            for name, value in body_schema.get("properties", {}).items()
            if not value.get("readOnly")
        )
        required_query = sorted(param["name"] for param in item["queryParams"] if param["required"])
        optional_query = sorted(param["name"] for param in item["queryParams"] if not param["required"])
        required_body = sorted(body_schema.get("required", []))
        return {
            "operationId": item["operationId"],
            "method": item["method"],
            "path": item["path"],
            "purpose": item["purpose"],
            "technicalFlowFamilies": item["technicalFlowFamilies"],
            "pathParams": [param["name"] for param in item["pathParams"]],
            "queryParams": [param["name"] for param in item["queryParams"]],
            "requiredQueryParams": required_query,
            "optionalQueryParams": optional_query,
            "bodyFields": body_fields,
            "requiredBodyFields": required_body,
            "allowedInputs": sorted(
                dict.fromkeys(
                    [*[param["name"] for param in item["pathParams"]], *[param["name"] for param in item["queryParams"]], *body_fields]
                    + (["body"] if item.get("requestBody") else [])
                )
            ),
            "inputTypes": self._raw_input_types(item),
            "requestBodyKind": item.get("requestBody", {}).get("kind"),
            "conformancePolicyKey": item.get("conformancePolicyKey"),
        }

    def _flow_policy_keys(self, item: dict[str, Any]) -> list[str]:
        policy_keys = {
            self.wrapper_catalog.get_command(command_name).get("conformancePolicyKey")
            for command_name in item.get("commandNames", [])
            if self.wrapper_catalog.has_command(command_name)
        }
        return sorted(policy_key for policy_key in policy_keys if policy_key)

    def _raw_input_types(self, item: dict[str, Any]) -> dict[str, Any]:
        hints: dict[str, Any] = {}
        for parameter in [*item["pathParams"], *item["queryParams"]]:
            description = parameter.get("description", "")
            hints[parameter["name"]] = {
                "section": parameter["in"],
                "type": parameter.get("type"),
                "format": parameter.get("format"),
                "enum": parameter.get("enum"),
                "defaultToTokenOwner": "token owner" in description.lower(),
                "hasDocumentedDefault": bool(parameter.get("default")) or "default" in description.lower(),
            }
        body_schema = next(iter(item.get("requestBody", {}).get("content", {}).values()), {})
        if item.get("requestBody"):
            hints["body"] = {
                "section": "body",
                "type": body_schema.get("type"),
                "format": body_schema.get("format"),
                "enum": body_schema.get("enum"),
                "defaultToTokenOwner": False,
                "hasDocumentedDefault": False,
            }
        for name, value in body_schema.get("properties", {}).items():
            if value.get("readOnly"):
                continue
            description = value.get("description", "")
            hints[name] = {
                "section": "body",
                "type": value.get("type"),
                "format": value.get("format"),
                "enum": value.get("enum"),
                "ref": value.get("ref"),
                "defaultToTokenOwner": "token owner" in description.lower(),
                "hasDocumentedDefault": bool(value.get("default")) or "default" in description.lower(),
            }
        return hints

    def _command_input_type_hints(self, item: dict[str, Any]) -> dict[str, Any]:
        raw_meta = self.raw_catalog.get(item["operationId"])
        raw_types = self._raw_input_types(raw_meta)
        hints: dict[str, Any] = {}
        for name, binding in item.get("inputBindings", {}).items():
            if binding.get("targetSection") == "control":
                continue
            target_name = binding.get("targetName")
            if binding.get("valueStrategy") == "body_merge":
                target_name = "body"
            if target_name not in raw_types:
                continue
            hints[name] = {
                **raw_types[target_name],
                "targetName": binding.get("targetName"),
                "valueStrategy": binding.get("valueStrategy"),
            }
        return hints
