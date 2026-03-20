from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .tasking import TaskAnalysis, TripletexCommand


class OpenAPIRegistryError(RuntimeError):
    pass


class OpenAPIValidationError(OpenAPIRegistryError):
    pass


@dataclass(frozen=True)
class OperationSpec:
    method: str
    template_path: str
    summary: str
    tags: tuple[str, ...]
    query_parameters: frozenset[str]
    required_query_parameters: frozenset[str]
    path_parameters: frozenset[str]
    request_body_required: bool
    allows_request_body: bool
    _path_pattern: re.Pattern[str]

    def matches(self, *, method: str, path: str) -> bool:
        return self.method == method and bool(self._path_pattern.fullmatch(path))

    def planner_hint(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.template_path,
            "summary": self.summary,
            "required_query_parameters": sorted(self.required_query_parameters),
            "allows_request_body": self.allows_request_body,
            "request_body_required": self.request_body_required,
        }


class TripletexOpenAPIRegistry:
    def __init__(self, operations: list[OperationSpec]):
        self.operations = operations

    @classmethod
    def from_default_spec(cls) -> "TripletexOpenAPIRegistry":
        return _load_default_registry()

    def validate_command(self, command: TripletexCommand) -> OperationSpec:
        operation = self.match_operation(method=command.method, path=command.path)
        if operation is None:
            raise OpenAPIValidationError(f"Command does not match any OpenAPI operation: {command.method} {command.path}")

        query_params = command.params or {}
        unknown_params = sorted(set(query_params) - set(operation.query_parameters))
        if unknown_params:
            raise OpenAPIValidationError(
                f"Unsupported query parameters for {command.method} {operation.template_path}: {', '.join(unknown_params)}"
            )

        missing_required = sorted(
            name for name in operation.required_query_parameters if query_params.get(name) in {None, ""}
        )
        if missing_required:
            raise OpenAPIValidationError(
                f"Missing required query parameters for {command.method} {operation.template_path}: {', '.join(missing_required)}"
            )

        if operation.request_body_required and command.json_body is None:
            raise OpenAPIValidationError(f"Request body is required for {command.method} {operation.template_path}")
        if not operation.allows_request_body and command.json_body is not None:
            raise OpenAPIValidationError(f"Request body is not allowed for {command.method} {operation.template_path}")

        return operation

    def match_operation(self, *, method: str, path: str) -> OperationSpec | None:
        normalized_method = method.upper()
        normalized_path = _normalize_path(path)
        for operation in self.operations:
            if operation.matches(method=normalized_method, path=normalized_path):
                return operation
        return None

    def planner_hints(
        self,
        *,
        target_resource: str | None = None,
        prefixes: tuple[str, ...] | None = None,
        limit: int | None = 36,
    ) -> list[dict[str, Any]]:
        selected_prefixes = prefixes or _resource_prefixes(target_resource)
        selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        if selected_prefixes:
            for prefix in selected_prefixes:
                for operation in self.operations:
                    if not operation.template_path.startswith(prefix):
                        continue
                    key = (operation.method, operation.template_path)
                    if key in seen:
                        continue
                    seen.add(key)
                    selected.append(operation.planner_hint())
                    if limit is not None and len(selected) >= limit:
                        break
                if limit is not None and len(selected) >= limit:
                    break

        if selected:
            return selected

        fallback: list[dict[str, Any]] = []
        for operation in self.operations:
            key = (operation.method, operation.template_path)
            if key in seen:
                continue
            seen.add(key)
            fallback.append(operation.planner_hint())
            fallback_limit = min(limit, 24) if limit is not None else None
            if fallback_limit is not None and len(fallback) >= fallback_limit:
                break
        return fallback


@lru_cache(maxsize=1)
def _load_default_registry() -> TripletexOpenAPIRegistry:
    spec_path = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OpenAPIRegistryError(f"OpenAPI spec file is missing: {spec_path}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAPIRegistryError(f"OpenAPI spec file is invalid JSON: {spec_path}") from exc

    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise OpenAPIRegistryError("OpenAPI spec is missing a valid 'paths' object.")

    operations: list[OperationSpec] = []
    for template_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "delete"}:
                continue
            if not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters") or []
            path_parameters = {
                parameter["name"]
                for parameter in parameters
                if isinstance(parameter, dict) and parameter.get("in") == "path" and "name" in parameter
            }
            query_parameters = {
                parameter["name"]
                for parameter in parameters
                if isinstance(parameter, dict) and parameter.get("in") == "query" and "name" in parameter
            }
            required_query_parameters = {
                parameter["name"]
                for parameter in parameters
                if isinstance(parameter, dict)
                and parameter.get("in") == "query"
                and parameter.get("required") is True
                and "name" in parameter
            }
            request_body = operation.get("requestBody")
            allows_request_body = isinstance(request_body, dict)
            request_body_required = bool(allows_request_body and request_body.get("required"))
            operations.append(
                OperationSpec(
                    method=method.upper(),
                    template_path=str(template_path),
                    summary=str(operation.get("summary") or operation.get("operationId") or "").strip(),
                    tags=tuple(str(tag) for tag in (operation.get("tags") or [])),
                    query_parameters=frozenset(query_parameters),
                    required_query_parameters=frozenset(required_query_parameters),
                    path_parameters=frozenset(path_parameters),
                    request_body_required=request_body_required,
                    allows_request_body=allows_request_body,
                    _path_pattern=_compile_path_pattern(str(template_path)),
                )
            )

    if not operations:
        raise OpenAPIRegistryError("No supported operations were loaded from OpenAPI spec.")

    operations.sort(
        key=lambda item: (
            _placeholder_count(item.template_path),
            -item.template_path.count("/"),
            item.template_path,
            item.method,
        )
    )
    return TripletexOpenAPIRegistry(operations)


def _compile_path_pattern(template_path: str) -> re.Pattern[str]:
    normalized = _normalize_path(template_path)
    parts = re.split(r"(\{[^/]+\})", normalized)
    pattern = "".join(r"[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part) for part in parts)
    return re.compile(f"^{pattern}$")


def _normalize_path(path: str) -> str:
    stripped = path.strip() or "/"
    if not stripped.startswith("/"):
        stripped = f"/{stripped}"
    return stripped.rstrip("/") or "/"


def _normalized_resource_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _split_identifier_words(value: str) -> tuple[str, ...]:
    cleaned = value.strip().strip("/")
    if not cleaned:
        return ()
    cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", cleaned)
    cleaned = re.sub(r"[_:/.\-]+", " ", cleaned)
    words = [word for word in cleaned.lower().split() if word and not word.startswith("{")]
    return tuple(words)


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized = keyword.strip().lower()
    if not normalized:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains_keyword(text, keyword) for keyword in keywords)


@lru_cache(maxsize=1)
def _primary_path_prefixes() -> tuple[str, ...]:
    spec_path = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    paths = spec.get("paths") or {}
    prefixes: set[str] = set()
    for template_path in paths:
        normalized = _normalize_path(str(template_path))
        for part in normalized.strip("/").split("/"):
            if not part or part.startswith("{"):
                continue
            prefixes.add(f"/{part.lstrip(':>')}")
            break
    return tuple(sorted(prefixes))


@lru_cache(maxsize=1)
def _primary_prefix_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for prefix in _primary_path_prefixes():
        lookup[_normalized_resource_key(prefix.lstrip("/"))] = prefix
    return lookup


@lru_cache(maxsize=1)
def _spec_resource_keywords() -> dict[str, tuple[str, ...]]:
    keywords: dict[str, tuple[str, ...]] = {}
    for prefix in _primary_path_prefixes():
        segment = prefix.lstrip("/")
        values = {
            segment.lower(),
            _normalized_resource_key(segment),
        }
        words = _split_identifier_words(segment)
        if len(words) == 1:
            values.add(words[0])
        elif words:
            values.add(" ".join(words))
        keywords[_normalized_resource_key(segment)] = tuple(sorted(value for value in values if value))
    return keywords


def _prefix_bundle(*prefixes: str) -> tuple[str, ...]:
    available = set(_primary_path_prefixes())
    selected: list[str] = []
    seen: set[str] = set()
    for prefix in prefixes:
        if prefix not in available or prefix in seen:
            continue
        seen.add(prefix)
        selected.append(prefix)
    return tuple(selected)


SEMANTIC_RESOURCE_PREFIXES: dict[str, tuple[str, ...]] = {
    "activity": _prefix_bundle("/activity", "/project"),
    "asset": _prefix_bundle("/asset", "/ledger"),
    "bank": _prefix_bundle("/bank", "/invoice", "/supplierInvoice", "/incomingInvoice", "/ledger"),
    "contact": _prefix_bundle("/contact", "/customer", "/supplier"),
    "customer": _prefix_bundle("/customer", "/deliveryAddress"),
    "department": _prefix_bundle("/department", "/attestation", "/company"),
    "documentarchive": _prefix_bundle("/documentArchive"),
    "employee": _prefix_bundle("/employee"),
    "event": _prefix_bundle("/event"),
    "incominginvoice": _prefix_bundle("/incomingInvoice", "/supplier", "/ledger"),
    "inventory": _prefix_bundle("/inventory", "/product"),
    "invoice": _prefix_bundle("/invoice", "/incomingInvoice", "/supplierInvoice", "/order"),
    "ledger": _prefix_bundle("/ledger"),
    "order": _prefix_bundle("/order", "/invoice"),
    "product": _prefix_bundle("/product"),
    "project": _prefix_bundle("/project", "/company"),
    "purchaseorder": _prefix_bundle("/purchaseOrder", "/supplier", "/product"),
    "salary": _prefix_bundle("/salary", "/employee"),
    "supplier": _prefix_bundle("/supplier", "/contact"),
    "supplierinvoice": _prefix_bundle("/supplierInvoice", "/supplier", "/ledger"),
    "timesheet": _prefix_bundle("/timesheet", "/activity", "/project", "/employee"),
    "travelexpense": _prefix_bundle("/travelExpense", "/employee", "/project"),
    "yearend": _prefix_bundle("/yearEnd", "/ledger"),
}


SEMANTIC_RESOURCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "activity": ("activity", "aktivitet", "activite", "actividad", "atividade"),
    "asset": ("asset", "fixed asset", "anleggsmiddel", "anlagegut"),
    "bank": ("bank", "bank payment", "payment batch", "betalingsbatch"),
    "contact": ("contact", "kontakt", "contacto"),
    "customer": ("customer", "kunde", "client", "cliente", "cliente", "org.nr", "organization number"),
    "department": ("department", "avdeling", "departamento", "abteilung"),
    "documentarchive": ("document archive", "dokumentsarkiv", "dokumentarkiv"),
    "employee": (
        "employee",
        "ansatt",
        "medarbeider",
        "employe",
        "empleado",
        "funcionario",
        "mitarbeiter",
        "project manager",
        "prosjektleiar",
        "projektleiter",
    ),
    "event": ("event", "webhook", "hendelse", "evento"),
    "incominginvoice": ("incoming invoice", "inngående faktura", "supplier voucher"),
    "inventory": ("inventory", "stock", "lager", "inventario", "estoque", "bestand"),
    "invoice": ("invoice", "faktura", "facture", "factura", "fatura", "credit note", "kreditnota", "rechnung"),
    "ledger": ("ledger", "voucher", "bilag", "posting", "reconciliation", "regnskap", "buchhaltung"),
    "order": ("order", "ordre", "pedido", "bestellung"),
    "product": ("product", "produkt", "item", "vare", "producto", "produto", "artikel", "artículo"),
    "project": ("project", "prosjekt", "projet", "proyecto", "projeto"),
    "purchaseorder": ("purchase order", "innkjøpsordre", "ordem de compra", "orden de compra"),
    "salary": ("salary", "payroll", "lønn", "lonn", "nomina", "nómina", "salario", "lohn", "gehalt"),
    "supplier": ("supplier", "leverandør", "leverandor", "proveedor", "fornecedor", "lieferant"),
    "supplierinvoice": ("supplier invoice", "leverandørfaktura", "leverandorfaktura"),
    "timesheet": (
        "timesheet",
        "time sheet",
        "register hours",
        "record hours",
        "hour registration",
        "time registration",
        "timer",
        "heures",
        "hours",
        "horas",
        "stunden",
    ),
    "travelexpense": ("travel expense", "reise", "travel report", "expense", "reisekost", "despesa", "gasto"),
    "yearend": ("year end", "årsoppgjør", "arsoppgjor", "jahresabschluss", "cierre anual"),
}


def _resource_prefixes(target_resource: str | None) -> tuple[str, ...]:
    key = _normalized_resource_key(target_resource or "other")
    if key in {"", "other"}:
        return _primary_path_prefixes()
    semantic_prefixes = SEMANTIC_RESOURCE_PREFIXES.get(key)
    if semantic_prefixes:
        return semantic_prefixes
    direct_prefix = _primary_prefix_lookup().get(key)
    if direct_prefix is not None:
        return (direct_prefix,)
    return _primary_path_prefixes()


def planner_prefixes_for_task(*, task_prompt: str, task_analysis: TaskAnalysis | None = None) -> tuple[str, ...]:
    text_parts = [task_prompt]
    field_keys: set[str] = set()

    if task_analysis is not None:
        text_parts.extend(
            (
                task_analysis.objective,
                task_analysis.task_family,
                task_analysis.operation,
                task_analysis.target_resource or "",
                " ".join(task_analysis.ambiguity_notes),
                " ".join(task_analysis.notes),
            )
        )
        field_keys.update(str(key).lower() for key in task_analysis.method_arguments)
        field_keys.update(str(key).lower() for key in task_analysis.search_hints)
        field_keys.update(str(key).lower() for key in task_analysis.payload_fields)

    text = " ".join(part for part in text_parts if part).lower()
    selected_prefixes: list[str] = []
    seen: set[str] = set()

    def add_resource(resource: str) -> None:
        for prefix in _resource_prefixes(resource):
            if prefix in seen:
                continue
            seen.add(prefix)
            selected_prefixes.append(prefix)

    if task_analysis is not None and task_analysis.target_resource:
        add_resource(task_analysis.target_resource)

    for resource, keywords in SEMANTIC_RESOURCE_KEYWORDS.items():
        if _contains_any_keyword(text, keywords):
            add_resource(resource)

    for resource, keywords in _spec_resource_keywords().items():
        if _contains_any_keyword(text, keywords):
            add_resource(resource)

    if any(key in field_keys for key in ("employeeemail", "employeenumber", "projectmanageremail")):
        add_resource("employee")
    if any(key in field_keys for key in ("departmentname", "departmentnumber")):
        add_resource("department")
    if any(key.startswith("orderline") for key in field_keys):
        add_resource("product")
        add_resource("order")
    if any(key in field_keys for key in ("projectname", "projectnumber")):
        add_resource("project")
    if any(key in field_keys for key in ("activityname", "activityid")):
        add_resource("activity")
    if any(key in field_keys for key in ("hours", "hourlyrate", "activityname", "employeeemail", "projectname")):
        add_resource("timesheet")
        add_resource("activity")
        add_resource("project")
        add_resource("employee")
    if any(key in field_keys for key in ("invoicenumber", "createinvoice", "paymenttypeid")):
        add_resource("customer")
        add_resource("order")
        add_resource("invoice")
    if any(key in field_keys for key in ("purchaseordernumber", "suppliername", "supplierid")):
        add_resource("purchaseorder")
        add_resource("supplier")
    if any(key in field_keys for key in ("accountnumber", "vattype", "paymenttype", "voucherid")):
        add_resource("ledger")
        add_resource("invoice")
    if any(key in field_keys for key in ("inventoryid", "stock", "countedquantity")):
        add_resource("inventory")
        add_resource("product")

    if not selected_prefixes:
        add_resource("other")
    return tuple(selected_prefixes)


def _placeholder_count(template_path: str) -> int:
    return len(re.findall(r"\{[^/]+\}", template_path))
