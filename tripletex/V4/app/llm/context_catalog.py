from __future__ import annotations

import re
from typing import Any
import unicodedata

from app.llm.contract_utils import input_names, split_required_inputs
from app.openapi_catalog import load_openapi_catalog
from app.raw import load_raw_catalog
from app.wrapper import load_wrapper_catalog


def _normalize_text(text: str) -> str:
    folded = (
        text.lower()
        .replace("ø", "o")
        .replace("æ", "ae")
        .replace("å", "a")
        .replace("ö", "o")
        .replace("ä", "a")
        .replace("ü", "u")
        .replace("ß", "ss")
    )
    normalized = unicodedata.normalize("NFKD", folded)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.replace("/", " ").replace("-", " ")


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", _normalize_text(text)) if len(token) > 2}


TOKEN_EQUIVALENTS = {
    "activity": {"activity", "activities", "aktivitet", "aktiviteter", "actividad", "actividades", "activite", "activites"},
    "account": {"account", "accounts", "konto", "konti", "cuenta", "cuentas", "compte", "comptes"},
    "attachment": {"attachment", "attachments", "attached", "vedlegg", "adjunto", "anhang", "piece", "receipt", "document", "file"},
    "create": {"create", "creates", "created", "new", "add", "register", "opprett", "lag", "crear", "creer", "neu"},
    "employee": {"employee", "employees", "ansatt", "empleado", "mitarbeiter", "employe", "personnel"},
    "import": {"import", "upload", "uploaded", "document", "documents", "receipt", "kvittering", "bookkeep", "bookkeeping", "bokfor"},
    "invoice": {"invoice", "invoices", "faktura", "fakturaer", "factura", "facturas", "rechnung", "rechnungen"},
    "ledger": {"ledger", "voucher", "vouchers", "bilag", "postering", "accounting", "bookkeeping", "bokfor"},
    "payment": {"payment", "payments", "pay", "paid", "betaling", "betale", "pago", "pagar", "zahl"},
    "project": {"project", "projects", "prosjekt", "proyecto", "projet"},
    "resolve": {"find", "search", "lookup", "check", "show", "sjekk", "finn", "buscar", "suche", "resolve"},
    "reverse": {"reverse", "reversal", "correct", "correction", "credit", "cancel", "reverseer", "reverser"},
    "supplier": {"supplier", "suppliers", "leverandor", "fornecedor", "proveedor", "lieferant", "fournisseur"},
    "timesheet": {"timesheet", "time", "timer", "horas", "heures", "stunden"},
    "travel_expense": {"travel", "reiseregning", "reise", "expense"},
    "voucher": {"voucher", "vouchers", "bilag", "postering", "ledger", "journal"},
}

ROOT_DOMAINS = (
    "activity",
    "timesheet",
    "supplier_invoice",
    "supplier",
    "invoice",
    "ledger",
    "project",
    "customer",
    "employee",
    "travel_expense",
    "department",
)


class ContextCatalog:
    def __init__(self) -> None:
        self.raw_catalog = load_raw_catalog()
        self.wrapper_catalog = load_wrapper_catalog()
        self.openapi_catalog = load_openapi_catalog()

    def build_slice(self, prompt: str) -> dict[str, Any]:
        prompt_tokens = self._expanded_prompt_tokens(prompt)
        flows = list(self.wrapper_catalog.flows.values())
        commands = list(self.wrapper_catalog.commands.values())
        raw_operations = self._rank_raw_operations(prompt_tokens)
        return {
            "routingRules": {
                "priority": [
                    "business_flow",
                    "friendly_alias",
                    "raw_operation",
                ],
                "ruleText": "Choose a business flow first when one fits, then a friendly command, then exact raw operationId fallback.",
            },
            "apiContract": {
                "contractVersion": "tripletex.api_contract.v1",
                "authority": (
                    "This is the authoritative allow-list. Only flow names in legalFlows and command names in legalCommands are valid. "
                    "Only listed inputs are allowed. Required inputs must be present before selecting that flow or command. "
                    "If a name is not listed exactly here, it is illegal."
                ),
                "selectorFamilies": self.wrapper_catalog.selector_families,
                "payloadFamilies": self.wrapper_catalog.payload_families,
                "legalFlowNames": [item["flowName"] for item in sorted(flows, key=lambda item: item["flowName"])],
                "legalCommandNames": [item["commandName"] for item in sorted(commands, key=lambda item: item["commandName"])],
                "legalFlows": [self._flow_contract_pack(item) for item in sorted(flows, key=lambda item: item["flowName"])],
                "legalCommands": [self._command_contract_pack(item) for item in sorted(commands, key=lambda item: item["commandName"])],
            },
            "rawApiContract": {
                "authority": "Every exact raw operationId listed here is legal, but only exact names are valid.",
                "legalOperationIds": sorted(self.raw_catalog.operations.keys()),
                "technicalFlowFamilies": sorted(
                    {item["technicalFlowFamily"] for item in self.raw_catalog.operations.values() if item.get("technicalFlowFamily")}
                ),
            },
            "policyCatalog": self.wrapper_catalog.policies,
            "selectorFamilies": self.wrapper_catalog.selector_families,
            "payloadFamilies": self.wrapper_catalog.payload_families,
            "flows": [self._flow_pack(item) for item in sorted(flows, key=lambda item: item["flowName"])],
            "commands": [self._command_pack(item) for item in sorted(commands, key=lambda item: item["commandName"])],
            "rawOperations": [self._raw_pack(item) for item in raw_operations[:80]],
        }

    def _rank(self, values: Any, prompt_tokens: set[str], render: Any) -> list[dict[str, Any]]:
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in values:
            haystack_tokens = _tokens(render(item))
            score = len(prompt_tokens & haystack_tokens)
            domain_tokens = _tokens(
                f"{item.get('domain', '')} {item.get('subdomain', '')} {' '.join(item.get('technicalFlowFamilies', []))}"
            )
            score += len(prompt_tokens & domain_tokens) * 2
            if item.get("domain") in prompt_tokens:
                score += 3
            if item.get("subdomain") in prompt_tokens:
                score += 2
            if score:
                scored.append((score, item))
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        return [value for _, value in scored]

    def _expanded_prompt_tokens(self, prompt: str) -> set[str]:
        tokens = _tokens(prompt)
        expanded = set(tokens)
        for canonical, synonyms in TOKEN_EQUIVALENTS.items():
            if tokens & synonyms:
                expanded.add(canonical)
                expanded.update(synonyms)
        prompt_text = _normalize_text(prompt)
        if (
            "supplier invoice" in prompt_text
            or "incoming invoice" in prompt_text
            or "leverandorfaktura" in prompt_text
        ):
            expanded.update({"supplier_invoice", "supplier", "invoice", "resolve"})
        if "project manager" in prompt_text or "prosjektleder" in prompt_text:
            expanded.update({"project", "employee"})
        if "how many hours" in prompt_text or ("worked" in tokens and "hours" in tokens) or ("jobbet" in tokens and "timer" in tokens):
            expanded.update({"timesheet", "total_hours", "resolve"})
        if "bookkeep" in prompt_text or "bookkeeping" in prompt_text or "bokfor" in prompt_text:
            expanded.update({"ledger", "voucher", "import", "attachment"})
        if "attachment" in prompt_text or "attached" in prompt_text or "vedlegg" in prompt_text or "vedlagt" in prompt_text:
            expanded.update({"attachment", "document", "import"})
        if "supplier_invoice" in expanded and "payment" in expanded:
            expanded.add("resolve")
        return expanded

    def _rank_raw_operations(self, prompt_tokens: set[str]) -> list[dict[str, Any]]:
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in self.raw_catalog.operations.values():
            score = self._raw_operation_score(item, prompt_tokens)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda item: (-item[0], item[1]["operationId"]))
        ranked = [item for _, item in scored]
        if not ranked:
            return []
        return self._blend_raw_operations(ranked, prompt_tokens)

    def _raw_operation_score(self, item: dict[str, Any], prompt_tokens: set[str]) -> int:
        purpose_tokens = _tokens(item.get("purpose", ""))
        alias_tokens = _tokens(" ".join(item.get("semanticAliases", [])))
        operation_tokens = _tokens(item.get("operationId", ""))
        family_tokens = _tokens(" ".join(item.get("technicalFlowFamilies", [])))
        domain_tokens = _tokens(f"{item.get('domain', '')} {item.get('subdomain', '')}")
        path_tokens = _tokens(item.get("path", ""))

        score = 0
        score += min(3, len(prompt_tokens & purpose_tokens)) * 2
        score += len(prompt_tokens & alias_tokens) * 2
        score += len(prompt_tokens & operation_tokens) * 3
        score += len(prompt_tokens & family_tokens) * 5
        score += len(prompt_tokens & domain_tokens) * 6
        score += len(prompt_tokens & path_tokens) * 2

        domain = item.get("domain", "")
        subdomain = item.get("subdomain", "")
        if domain in prompt_tokens:
            score += 6
        if subdomain and subdomain in prompt_tokens:
            score += 4
        if domain in prompt_tokens and subdomain == "root":
            score += 2

        method = str(item.get("method", "")).upper()
        if "create" in prompt_tokens and method == "POST":
            score += 3
        if "resolve" in prompt_tokens and method == "GET":
            score += 2
        if "payment" in prompt_tokens and method in {"POST", "PUT"}:
            score += 3
        if "reverse" in prompt_tokens and method in {"POST", "PUT"}:
            score += 3
        if "import" in prompt_tokens and method == "POST":
            score += 2
        if "total_hours" in prompt_tokens and "total_hours" in family_tokens:
            score += 10

        if {"attachment", "import"} & prompt_tokens:
            if item.get("requestBody", {}).get("kind") == "multipart":
                score += 8
            if {"document", "upload", "import"} & (purpose_tokens | alias_tokens | path_tokens):
                score += 8

        if "reverse" in prompt_tokens:
            if "reverse" in (family_tokens | alias_tokens | operation_tokens):
                score += 8
            elif "create" in family_tokens:
                score -= 3

        if "payment" in prompt_tokens:
            if "payment" in (family_tokens | alias_tokens | operation_tokens):
                score += 6
            elif "create" in family_tokens:
                score -= 2

        if domain in prompt_tokens and subdomain not in {"", "root"}:
            subdomain_tokens = _tokens(subdomain)
            if subdomain_tokens and not (prompt_tokens & subdomain_tokens):
                score -= 1
        return score

    def _blend_raw_operations(self, ranked: list[dict[str, Any]], prompt_tokens: set[str]) -> list[dict[str, Any]]:
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

        for domain in self._domain_hints(prompt_tokens):
            add([item for item in ranked if self._matches_domain_hint(item, domain)], limit=12)
        add(ranked, limit=80)
        return selected

    def _domain_hints(self, prompt_tokens: set[str]) -> list[str]:
        scored_hints: list[tuple[int, str]] = []
        for domain in ROOT_DOMAINS:
            if domain not in prompt_tokens:
                continue
            score = 1
            if domain == "timesheet" and "total_hours" in prompt_tokens:
                score += 5
            if domain == "supplier_invoice" and "payment" in prompt_tokens:
                score += 4
            if domain == "ledger" and {"voucher", "attachment", "import"} & prompt_tokens:
                score += 6
            if domain == "project" and "create" in prompt_tokens:
                score += 3
            if domain == "activity" and "create" in prompt_tokens:
                score += 3
            scored_hints.append((score, domain))
        scored_hints.sort(key=lambda item: (-item[0], item[1]))
        hints = [domain for _, domain in scored_hints]
        if "voucher" in prompt_tokens and "ledger" not in hints:
            hints.append("ledger")
        return hints

    def _matches_domain_hint(self, item: dict[str, Any], domain: str) -> bool:
        if item.get("domain") == domain:
            return True
        family_tokens = _tokens(" ".join(item.get("technicalFlowFamilies", [])))
        if domain in family_tokens:
            return True
        return domain in _tokens(item.get("path", ""))

    def _flow_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "flowName": item["flowName"],
            "inputs": item["inputs"],
            "inputSemantics": item.get("inputSemantics", {}),
            "useWhen": item["useWhen"],
            "steps": item["steps"],
            "commandNames": item["commandNames"],
            "policyKeys": self._flow_policy_keys(item),
        }

    def _command_pack(self, item: dict[str, Any]) -> dict[str, Any]:
        body_fields = self._command_body_fields(item)
        return {
            "commandName": item["commandName"],
            "operationId": item["operationId"],
            "purpose": item["purpose"],
            "wrapperInputs": item["inputs"],
            "bodyFields": body_fields,
            "allInputs": self._command_legal_inputs(item),
            "inputSpec": item.get("inputSpec"),
            "inputSemantics": item.get("inputSemantics", {}),
            "inputTypeHints": self._command_input_type_hints(item),
            "selectorFamily": item.get("selectorFamily"),
            "technicalFlowFamily": item["technicalFlowFamily"],
            "safetyClass": item["safetyClass"],
            "conformancePolicyKey": item.get("conformancePolicyKey"),
            "availability": self.openapi_catalog.capability_profile(item["operationId"]),
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
            "availability": self.openapi_catalog.capability_profile(item["operationId"]),
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
            "availability": self.openapi_catalog.capability_profile(item["operationId"]),
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
