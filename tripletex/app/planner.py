from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from typing import Any

from .generated_methods import GeneratedAPIMethodRegistry
from .internal_tasks import planner_method_hints, validate_task_analysis_contract, workflow_prefixes_for_method
from .openapi_registry import TripletexOpenAPIRegistry, planner_prefixes_for_task
from .spec_runtime import planner_runtime_hints
from .tasking import AttachmentContext, PlannerDecision, TaskAnalysis

logger = logging.getLogger(__name__)


ANALYSIS_PROMPT = """You are preparing a deterministic Tripletex API execution.

Return JSON only. No markdown fences.

Produce exactly one JSON object with this shape:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "short description of desired end state",
  "method_name": "supported method name from method_catalog",
  "method_arguments": {"key": "value"},
  "missing_required_arguments": ["argumentName"],
  "task_family": "resource.operation style label such as customer.create",
  "operation": "create | update | delete | invoice | register_payment | correct | reverse | search | other",
  "target_resource": "Tripletex resource family such as employee, customer, product, order, invoice, travelExpense, project, department, activity, timesheet, ledger, purchaseOrder, salary, bank, inventory, asset, yearEnd, documentArchive, or another top-level OpenAPI family",
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
- your primary job is to translate the user's natural language request into one supported internal method call when possible
- you are the only layer that should interpret human language; downstream code only sees structured fields
- choose the narrowest method_name from method_catalog that can satisfy the requested workflow without semantic loss
- downstream code will not semantically rewrite a broad method into a narrower one; it only validates and executes your structured choice
- method_catalog entries expose execution_strategy:
  - prefer execution_strategy=curated_router when that workflow fully covers the request
  - choose execution_strategy=openapi_wrapper when no narrower curated workflow covers the request exactly
- method_catalog entries also expose coverage_status:
  - prefer coverage_status=coded whenever it can satisfy the request without semantic loss
  - choose coverage_status=wrapper_only only when the task is simple enough to be executed from structured search_hints and payload_fields
- method_catalog entries may also expose planner_choose_when and planner_avoid_when:
  - treat planner_choose_when as positive routing guidance
  - treat planner_avoid_when as hard constraints unless the user request clearly falls outside the described cases
- method_name must always be a concrete value from method_catalog
- always emit contract_version exactly as "tripletex.task_analysis.v1"
- method_arguments must use the exact argument names from the chosen method hint
- extract only arguments supported by the chosen method; do not emit API paths, endpoint names, or query parameters
- if a required argument is not present in the prompt or attachments, do not guess it; list it in missing_required_arguments
- if the prompt is not in English, translate its meaning internally but still emit canonical method_name and argument names in English
- runtime_context.current_date is the authoritative anchor for resolving relative dates like today, this month, next month, or last month into exact ISO dates and concrete month/year values
- when an email uniquely identifies a person, prefer the email and do not invent firstName/lastName unless they are explicit
- when a curated workflow exists for the structured task, choose that curated workflow directly; do not emit a Run*OpenAPIWorkflow wrapper for the same task family
- for outgoing invoice payment requests, prefer RegisterInvoicePayment and use customerName/customerOrganizationNumber/invoiceAmount/currencyCode/date window when invoiceNumber is missing
- for travel-expense requests, prefer RunTravelExpenseWorkflow and emit departureDate/returnDate only when explicit
- for month-end closing requests, prefer RunMonthEndClosingWorkflow and fill its required ledger/account arguments directly from the prompt when present
- for ledger comparison requests that create internal projects/activities from top expense-account increases, prefer RunExpenseIncreaseProjectWorkflow and emit both baseline and comparison date ranges
- for payroll tasks, prefer RunSalaryPayrollWorkflow and emit exact date, month, year, employee identity, and non-empty salaryLines or payslips
- for bank-statement reconciliation tasks, prefer RunBankReconciliationWorkflow and emit non-empty statementEntries with paymentDate, amount, direction, and customer/supplier/invoice hints per entry whenever they can be derived from the prompt or attachments
- infer the likely Tripletex workflow family from the prompt and attachments for fallback logging and full-catalog execution planning
- keep search_hints limited to values useful for API lookups
- keep payload_fields limited to values likely needed for creation or update
- mark risk_level=high for destructive or ambiguous tasks
- do not invent facts that are not supported by the prompt or attachments
- do not use closest-match curated methods when the request actually requires timesheet registration, project billing from registered hours, ledger correction, reconciliation, or any other extra workflow steps not covered by that curated method
- target_resource may be any Tripletex OpenAPI resource family, not only the example values above

Examples:
1. Travel expense in any language with employee email, title, duration, per diem, and expenses but no explicit travel dates:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Register a travel expense report",
  "method_name": "RunTravelExpenseWorkflow",
  "method_arguments": {
    "title": "Conference Stavanger",
    "employeeEmail": "hugo.martin@example.org",
    "durationDays": 5,
    "destination": "Conference Stavanger",
    "perDiemRate": 800,
    "perDiemCount": 5,
    "expenses": [{"description": "Flight ticket", "amount": 7700}, {"description": "Taxi", "amount": 600}]
  },
  "missing_required_arguments": ["departureDate", "returnDate"],
  "task_family": "travelexpense.create",
  "operation": "create",
  "target_resource": "travelExpense",
  "detected_language": "French",
  "search_hints": {"employeeEmail": "hugo.martin@example.org"},
  "payload_fields": {"title": "Conference Stavanger", "durationDays": 5, "perDiemRate": 800, "perDiemCount": 5},
  "attachment_required": false,
  "ambiguity_notes": ["Travel dates are missing."],
  "risk_level": "low",
  "completion_signals": ["A travel expense is created for the employee."],
  "notes": []
}

2. Currency invoice payment registration with customer identified by name and organization number:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Register invoice payment and resulting currency difference",
  "method_name": "RegisterInvoicePayment",
  "method_arguments": {
    "customerName": "Havbris AS",
    "customerOrganizationNumber": "887674973",
    "paidAmount": 17724,
    "currencyCode": "EUR",
    "invoiceAmount": 17724
  },
  "missing_required_arguments": [],
  "task_family": "invoice.register_payment",
  "operation": "register_payment",
  "target_resource": "invoice",
  "detected_language": "Norwegian",
  "search_hints": {"customerName": "Havbris AS", "customerOrganizationNumber": "887674973"},
  "payload_fields": {"paidAmount": 17724, "currencyCode": "EUR", "invoiceAmount": 17724},
  "attachment_required": false,
  "ambiguity_notes": [],
  "risk_level": "medium",
  "completion_signals": ["The outgoing invoice payment is registered."],
  "notes": ["Use customer lookup when invoiceNumber is not given."]
}

3. Compare two months and create internal projects and activities from the top expense-account increases:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Create internal projects and activities from the largest expense-account increases",
  "method_name": "RunExpenseIncreaseProjectWorkflow",
  "method_arguments": {
    "baselineDateFrom": "2026-01-01",
    "baselineDateTo": "2026-01-31",
    "comparisonDateFrom": "2026-02-01",
    "comparisonDateTo": "2026-02-28",
    "topCount": 3,
    "isInternal": true,
    "createActivity": true
  },
  "missing_required_arguments": [],
  "task_family": "project.create",
  "operation": "other",
  "target_resource": "project",
  "detected_language": "Portuguese",
  "search_hints": {"baselineDateFrom": "2026-01-01", "baselineDateTo": "2026-01-31", "comparisonDateFrom": "2026-02-01", "comparisonDateTo": "2026-02-28"},
  "payload_fields": {"isInternal": true, "createActivity": true},
  "attachment_required": false,
  "ambiguity_notes": [],
  "risk_level": "medium",
  "completion_signals": ["Three internal projects and matching activities are created."],
  "notes": []
}

4. Enable department accounting through company settings:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Enable department accounting",
  "method_name": "RunCompanyOpenAPIWorkflow",
  "method_arguments": {"moduleDepartmentAccounting": true},
  "missing_required_arguments": [],
  "task_family": "department.enable_module",
  "operation": "update",
  "target_resource": "company",
  "detected_language": "English",
  "search_hints": {},
  "payload_fields": {"moduleDepartmentAccounting": true},
  "attachment_required": false,
  "ambiguity_notes": [],
  "risk_level": "medium",
  "completion_signals": ["Department accounting is enabled in company settings."],
  "notes": []
}

5. Employee onboarding from an attached employment contract in Portuguese:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Create a new employee from the employment contract",
  "method_name": "RunEmployeeOnboardingWorkflow",
  "method_arguments": {
    "firstName": "Miguel",
    "lastName": "Costa",
    "email": "miguel.costa@example.org",
    "dateOfBirth": "1981-11-06",
    "nationalIdentityNumber": "06118185755",
    "bankAccountNumber": "63096583860",
    "departmentName": "Innkjøp",
    "occupationCode": "4110",
    "annualSalary": 720000,
    "percentageOfFullTimeEquivalent": 100,
    "startDate": "2026-04-01",
    "employmentForm": "Fast stilling",
    "remunerationType": "Fastlønn (månedlig)"
  },
  "missing_required_arguments": [],
  "task_family": "employee.create",
  "operation": "create",
  "target_resource": "employee",
  "detected_language": "Portuguese",
  "search_hints": {"email": "miguel.costa@example.org", "nationalIdentityNumber": "06118185755"},
  "payload_fields": {"departmentName": "Innkjøp", "occupationCode": "4110", "annualSalary": 720000, "startDate": "2026-04-01"},
  "attachment_required": true,
  "ambiguity_notes": [],
  "risk_level": "low",
  "completion_signals": ["The employee is created with employment details matching the contract."],
  "notes": []
}

6. Delete a travel expense in Spanish:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Delete a travel expense report",
  "method_name": "RunTravelExpenseWorkflow",
  "method_arguments": {
    "title": "Conferencia Stavanger",
    "employeeEmail": "hugo.martin@example.org",
    "departureDate": "2026-03-10",
    "returnDate": "2026-03-14"
  },
  "missing_required_arguments": [],
  "task_family": "travelexpense.delete",
  "operation": "delete",
  "target_resource": "travelExpense",
  "detected_language": "Spanish",
  "search_hints": {"employeeEmail": "hugo.martin@example.org"},
  "payload_fields": {"title": "Conferencia Stavanger", "departureDate": "2026-03-10", "returnDate": "2026-03-14"},
  "attachment_required": false,
  "ambiguity_notes": [],
  "risk_level": "high",
  "completion_signals": ["The matching travel expense report is removed."],
  "notes": []
}

7. Reverse a wrongly registered payment in Norwegian:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Reverse an outgoing invoice payment",
  "method_name": "RunInvoicePaymentReversalWorkflow",
  "method_arguments": {
    "customerName": "Havbris AS",
    "customerOrganizationNumber": "887674973",
    "invoiceNumber": "2026-1044",
    "reversalDate": "2026-03-21"
  },
  "missing_required_arguments": [],
  "task_family": "invoice.reverse_payment",
  "operation": "reverse",
  "target_resource": "invoice",
  "detected_language": "Norwegian",
  "search_hints": {"customerName": "Havbris AS", "customerOrganizationNumber": "887674973", "invoiceNumber": "2026-1044"},
  "payload_fields": {"reversalDate": "2026-03-21"},
  "attachment_required": false,
  "ambiguity_notes": [],
 "risk_level": "medium",
  "completion_signals": ["The payment voucher is reversed and the invoice is open again."],
  "notes": []
}

8. Run payroll for this month in French, using runtime_context.current_date to resolve the period:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Run payroll for Jules Leroy for March 2026",
  "method_name": "RunSalaryPayrollWorkflow",
  "method_arguments": {
    "employeeEmail": "jules.leroy@example.org",
    "date": "2026-03-21",
    "month": 3,
    "year": 2026,
    "salaryLines": [
      {"salaryTypeName": "Fastlønn", "amount": 56950},
      {"salaryTypeName": "Bonus", "amount": 9350, "description": "Prime unique"}
    ]
  },
  "missing_required_arguments": [],
  "task_family": "salary.create",
  "operation": "create",
  "target_resource": "salary",
  "detected_language": "French",
  "search_hints": {"employeeEmail": "jules.leroy@example.org"},
  "payload_fields": {"date": "2026-03-21", "month": 3, "year": 2026},
  "attachment_required": false,
  "ambiguity_notes": [],
  "risk_level": "medium",
  "completion_signals": ["A salary transaction is created for the employee for the resolved payroll period."],
  "notes": []
}

9. Reconcile an attached bank statement against open invoices:
{
  "contract_version": "tripletex.task_analysis.v1",
  "objective": "Match bank statement entries against open customer and supplier invoices",
  "method_name": "RunBankReconciliationWorkflow",
  "method_arguments": {
    "statementEntries": [
      {
        "paymentDate": "2026-03-20",
        "direction": "incoming",
        "amount": 17724,
        "invoiceNumber": "2026-1044",
        "customerName": "Havbris AS",
        "customerOrganizationNumber": "887674973"
      },
      {
        "paymentDate": "2026-03-20",
        "direction": "outgoing",
        "amount": 80375,
        "invoiceNumber": "INV-2026-1194",
        "supplierName": "Rio Azul Lda",
        "supplierOrganizationNumber": "966170042",
        "partialPayment": false
      }
    ],
    "fromDate": "2026-03-20",
    "toDate": "2026-03-20"
  },
  "missing_required_arguments": [],
  "task_family": "bank.reconcile",
  "operation": "other",
  "target_resource": "bank",
  "detected_language": "English",
  "search_hints": {"fromDate": "2026-03-20", "toDate": "2026-03-20"},
  "payload_fields": {"statementEntries": [{"paymentDate": "2026-03-20", "direction": "incoming", "amount": 17724}]},
  "attachment_required": true,
  "ambiguity_notes": [],
  "risk_level": "high",
  "completion_signals": ["The statement entries are matched and the corresponding invoice payments are registered."],
  "notes": []
}
"""

EXECUTION_PROMPT = """You are a deterministic Tripletex v2 method planner.

Return JSON only. No markdown fences.

Allowed response shapes:
1. Call one generated API method:
{
  "kind": "method",
  "reason": "short explanation",
  "method_call": {
    "method_name": "CustomerSearch",
    "arguments": {
      "organizationNumber": "845903077",
      "fields": "id,name"
    }
  }
}

2. Finish:
{
  "kind": "finish",
  "reason": "short explanation"
}

Rules:
- use only method_name values listed in api_method_hints
- method arguments must match the generated method signature exactly
- active_method_name identifies the workflow currently owning execution; prefer API methods that advance that workflow rather than rediscovering a new one
- task_prompt is the authoritative user intent; if task_analysis reflects a rejected curated shortcut or incomplete extraction, recover from task_prompt instead of following the shortcut
- the task may require combining multiple method calls across different Tripletex resource families; choose the single best next generated method that advances that workflow
- treat the OpenAPI spec as authoritative; the examples docs may use simplified parameter names or flows
- api_method_hints may contain the full matched generated-method catalog for the selected resources; absence of a curated shortcut does not imply lack of support
- do not emit raw HTTP methods, raw paths, or ad-hoc endpoint names
- do not invent a generic payment method; use the canonical generated invoice or supplier-invoice payment methods
- when a search method requires a date window, always include the required date arguments
- use payment-type, entitlement, and module-related methods when the task requires them
- use timesheet, activity, project, customer, order, invoice, payment, travel, and ledger methods together when the workflow spans those resources
- when a POST or PUT body references an existing Tripletex object, resolve that object first and use its internal id in the nested body object unless the method hint clearly describes a raw object-creation payload
- when a method uses a raw or array body, inspect the schema metadata in api_method_hints and build the body accordingly instead of guessing a flat object
- prefer methods listed in api_method_hints
- prefer exact searches before create or update if duplicates are possible
- keep API calls efficient and minimal
- reuse earlier responses instead of repeating searches
- do not finish until the intended state change is complete
- if a request failed, use the error payload to repair the next method call instead of guessing broadly
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
        task_prompt: str,
        task_analysis: TaskAnalysis,
        attachments: list[AttachmentContext],
        history: list[dict[str, Any]],
        remaining_steps: int,
        active_method_name: str | None = None,
        active_workflow_context: dict[str, Any] | None = None,
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
            method_name="RunGenericOpenAPIWorkflow",
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
        task_prompt: str,
        task_analysis: TaskAnalysis,
        attachments: list[AttachmentContext],
        history: list[dict[str, Any]],
        remaining_steps: int,
        active_method_name: str | None = None,
        active_workflow_context: dict[str, Any] | None = None,
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
        self.generated_methods = GeneratedAPIMethodRegistry.from_default_spec()

    def analyze_task(
        self,
        *,
        task_prompt: str,
        attachments: list[AttachmentContext],
    ) -> TaskAnalysis:
        started_at = time.monotonic()
        analysis_prefixes = planner_prefixes_for_task(task_prompt=task_prompt)
        payload = {
            "task_prompt": task_prompt,
            "runtime_context": {
                "current_date": date.today().isoformat(),
            },
            "attachments": [attachment.model_dump(mode="json") for attachment in attachments],
            "method_catalog": planner_method_hints(),
            "openapi_endpoint_hints": self.registry.planner_hints(prefixes=analysis_prefixes, limit=160),
            "api_method_hints": self.generated_methods.planner_hints(prefixes=analysis_prefixes, limit=None),
            "spec_runtime_hints": planner_runtime_hints(),
        }
        logger.info(
            "planner.analysis.start model=%s attachments=%s prompt_chars=%s analysis_prefixes=%s method_catalog=%s endpoint_hints=%s api_method_hints=%s",
            self.model_name,
            len(attachments),
            len(task_prompt),
            list(analysis_prefixes),
            len(payload["method_catalog"]),
            len(payload["openapi_endpoint_hints"]),
            len(payload["api_method_hints"]),
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
            analysis = TaskAnalysis.model_validate(_extract_json(response_text))
        except Exception as exc:
            logger.exception("planner.analysis.parse_failed response_preview=%r", response_text[:1200])
            raise PlannerError(f"Failed to parse task analysis: {response_text!r}") from exc
        try:
            validate_task_analysis_contract(analysis)
        except ValueError as exc:
            logger.exception("planner.analysis.contract_invalid response_preview=%r", response_text[:1200])
            raise PlannerError(f"Planner contract violation: {exc}") from exc
        logger.info(
            "planner.analysis.method method=%s missing_required_arguments=%s task_family=%s target_resource=%s search_hints=%s payload_fields=%s notes=%s",
            analysis.method_name,
            analysis.missing_required_arguments,
            analysis.task_family,
            analysis.target_resource,
            sorted(analysis.search_hints.keys()),
            sorted(analysis.payload_fields.keys()),
            analysis.notes[:4],
        )
        return analysis

    def next_step(
        self,
        *,
        task_prompt: str,
        task_analysis: TaskAnalysis,
        attachments: list[AttachmentContext],
        history: list[dict[str, Any]],
        remaining_steps: int,
        active_method_name: str | None = None,
        active_workflow_context: dict[str, Any] | None = None,
    ) -> PlannerDecision:
        started_at = time.monotonic()
        planner_prefixes = planner_prefixes_for_task(
            task_prompt=task_prompt,
            task_analysis=task_analysis,
        )
        if active_method_name:
            planner_prefixes = _merge_prefixes(
                workflow_prefixes_for_method(active_method_name, task_analysis=task_analysis),
                planner_prefixes,
            )
        payload = {
            "task_prompt": task_prompt,
            "task_analysis": task_analysis.model_dump(mode="json"),
            "active_method_name": active_method_name,
            "active_workflow_context": active_workflow_context or {},
            "attachments": [attachment.model_dump(mode="json") for attachment in attachments],
            "history": history[-6:],
            "remaining_steps": remaining_steps,
            "openapi_endpoint_hints": self.registry.planner_hints(prefixes=planner_prefixes, limit=200),
            "api_method_hints": self.generated_methods.planner_hints(prefixes=planner_prefixes, limit=None),
            "spec_runtime_hints": planner_runtime_hints(task_analysis),
        }
        logger.info(
            "planner.step.start model=%s task_family=%s remaining_steps=%s history_entries=%s active_method=%s planner_prefixes=%s endpoint_hints=%s api_method_hints=%s workflow_context=%s history_tail=%s",
            self.model_name,
            task_analysis.task_family,
            remaining_steps,
            len(history),
            active_method_name,
            list(planner_prefixes),
            len(payload["openapi_endpoint_hints"]),
            len(payload["api_method_hints"]),
            _trim_payload(active_workflow_context or {}),
            _history_tail_signature(history),
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
                "planner.step.action method=%s path=%s params=%s json=%s reason=%r",
                action.method,
                action.path,
                _trim_payload(action.params),
                _trim_payload(action.json_body),
                decision.reason[:240],
            )
            if self.registry.match_operation(method=action.method, path=action.path) is None:
                logger.warning(
                    "planner.step.action_not_in_spec method=%s path=%s target_resource=%s",
                    action.method,
                    action.path,
                    task_analysis.target_resource,
                )
        elif decision.kind == "method":
            method_call = decision.method_call
            if method_call is None:
                raise PlannerError("Planner returned kind=method without a method_call payload.")
            logger.info(
                "planner.step.method method_name=%s arguments=%s reason=%r",
                method_call.method_name,
                _trim_payload(method_call.arguments),
                decision.reason[:240],
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

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config={
                    "temperature": 0,
                    "response_mime_type": "application/json",
                },
            )
        except Exception as exc:
            raise PlannerError(f"Vertex AI planning request failed: {exc}") from exc
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


def _merge_prefixes(*groups: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for prefix in group:
            if prefix in seen:
                continue
            seen.add(prefix)
            merged.append(prefix)
    return tuple(merged)


def _trim_payload(value: Any, *, max_depth: int = 3, max_items: int = 5) -> Any:
    if max_depth <= 0:
        return "<truncated>"
    if isinstance(value, dict):
        trimmed: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                trimmed["..."] = "<truncated>"
                break
            trimmed[str(key)] = _trim_payload(item, max_depth=max_depth - 1, max_items=max_items)
        return trimmed
    if isinstance(value, list):
        return [_trim_payload(item, max_depth=max_depth - 1, max_items=max_items) for item in value[:max_items]]
    return value


def _history_tail_signature(history: list[dict[str, Any]], *, max_entries: int = 4) -> list[dict[str, Any]]:
    tail: list[dict[str, Any]] = []
    for entry in history[-max_entries:]:
        request = entry.get("request") or {}
        item: dict[str, Any] = {
            "reason": str(entry.get("reason") or "")[:120],
            "method": request.get("method") or request.get("kind"),
            "path": request.get("path") or request.get("method_name"),
        }
        if "response" in entry:
            item["response"] = _payload_signature(entry.get("response"))
        if "error" in entry:
            item["error"] = _trim_payload(entry.get("error"), max_depth=2, max_items=4)
        tail.append(item)
    return tail


def _payload_signature(value: Any) -> Any:
    if isinstance(value, dict):
        summary: dict[str, Any] = {"type": "dict", "keys": list(value.keys())[:8]}
        if isinstance(value.get("values"), list):
            summary["values_count"] = len(value["values"])
        if isinstance(value.get("value"), dict) and value["value"].get("id") not in {None, ""}:
            summary["value_id"] = value["value"]["id"]
        return summary
    if isinstance(value, list):
        return {"type": "list", "items": len(value)}
    return {"type": type(value).__name__, "value": str(value)[:160]}


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()
