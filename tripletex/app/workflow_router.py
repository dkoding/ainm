from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from .internal_tasks import FlowKind, InternalTask
from .openapi_registry import ResourceCapability, TripletexOpenAPIRegistry
from .spec_runtime import (
    best_effort_amount,
    best_effort_date_window,
    best_effort_payment_type_description,
    best_effort_payment_type_id,
    combine_analysis_text,
    default_action_date,
    infer_entitlement_template,
    is_employee_admin_task,
    is_invoice_payment_task,
    lookup_analysis_value,
    resolved_invoice_from_history,
)
from .tasking import PlannedAction, PlannerDecision, TaskAnalysis

logger = logging.getLogger(__name__)


class DeterministicWorkflowRouter:
    def __init__(self, registry: TripletexOpenAPIRegistry | None = None) -> None:
        self.registry = registry or TripletexOpenAPIRegistry.from_default_spec()

    def next_step(
        self,
        *,
        internal_task: InternalTask,
        task_prompt: str | None = None,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        del task_prompt
        if not internal_task.is_supported:
            logger.info(
                "workflow.step.unsupported method=%s flow_kind=%s target_resource=%s",
                internal_task.method_name,
                internal_task.flow_kind.value,
                internal_task.target_resource,
            )
            return None

        route_name: str | None = None
        route_fn = None

        if internal_task.flow_kind is FlowKind.SALES_WORKFLOW:
            route_name = "_next_sales_workflow"
            route_fn = lambda: self._next_sales_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.SUPPLIER_INVOICE_WORKFLOW:
            route_name = "_next_supplier_invoice_workflow"
            route_fn = lambda: self._next_supplier_invoice_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.INVOICE_CREDIT_NOTE:
            route_name = "_next_invoice_credit_note_workflow"
            route_fn = lambda: self._next_invoice_credit_note_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.PROJECT_TIME_INVOICE_WORKFLOW:
            route_name = "_next_project_time_invoice_workflow"
            route_fn = lambda: self._next_project_time_invoice_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.PROJECT_LIFECYCLE_WORKFLOW:
            route_name = "_next_project_lifecycle_workflow"
            route_fn = lambda: self._next_project_lifecycle_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.INVOICE_REGISTER_PAYMENT:
            route_name = "_next_invoice_payment"
            route_fn = lambda: self._next_invoice_payment(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.INVOICE_PAYMENT_REVERSAL_WORKFLOW:
            route_name = "_next_invoice_payment_reversal_workflow"
            route_fn = lambda: self._next_invoice_payment_reversal_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.EMPLOYEE_ADMIN:
            route_name = "_next_employee_admin"
            route_fn = lambda: self._next_employee_admin(
                internal_task=internal_task,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.EMPLOYEE_ONBOARDING_WORKFLOW:
            route_name = "_next_employee_onboarding_workflow"
            route_fn = lambda: self._next_employee_onboarding_workflow(
                internal_task=internal_task,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.TRAVEL_EXPENSE_WORKFLOW:
            route_name = "_next_travel_expense_workflow"
            route_fn = lambda: self._next_travel_expense_workflow(
                internal_task=internal_task,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.MONTH_END_CLOSING_WORKFLOW:
            route_name = "_next_month_end_closing_workflow"
            route_fn = lambda: self._next_month_end_closing_workflow(
                internal_task=internal_task,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.EXPENSE_INCREASE_PROJECT_WORKFLOW:
            route_name = "_next_expense_increase_project_workflow"
            route_fn = lambda: self._next_expense_increase_project_workflow(
                internal_task=internal_task,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.SALARY_PAYROLL_WORKFLOW:
            route_name = "_next_salary_payroll_workflow"
            route_fn = lambda: self._next_salary_payroll_workflow(
                internal_task=internal_task,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.BANK_RECONCILIATION_WORKFLOW:
            route_name = "_next_bank_reconciliation_workflow"
            route_fn = lambda: self._next_bank_reconciliation_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )
        elif internal_task.flow_kind is FlowKind.EMPLOYEE_UPSERT:
            route_name = "_next_employee_upsert"
            route_fn = lambda: self._next_employee_upsert(internal_task=internal_task, history=history)
        elif internal_task.flow_kind is FlowKind.CUSTOMER_UPSERT:
            route_name = "_next_customer_upsert"
            route_fn = lambda: self._next_customer_upsert(internal_task=internal_task, history=history)
        elif internal_task.flow_kind is FlowKind.SUPPLIER_UPSERT:
            route_name = "_next_supplier_upsert"
            route_fn = lambda: self._next_supplier_upsert(internal_task=internal_task, history=history)
        elif internal_task.flow_kind is FlowKind.PRODUCT_UPSERT:
            route_name = "_next_product_upsert"
            route_fn = lambda: self._next_product_upsert(internal_task=internal_task, history=history)
        elif internal_task.flow_kind is FlowKind.DEPARTMENT_UPSERT:
            route_name = "_next_department_upsert"
            route_fn = lambda: self._next_department_upsert(internal_task=internal_task, history=history)
        elif internal_task.flow_kind is FlowKind.PROJECT_UPSERT:
            route_name = "_next_project_upsert"
            route_fn = lambda: self._next_project_upsert(internal_task=internal_task, history=history)
        elif internal_task.flow_kind is FlowKind.LEDGER_DIMENSION_WORKFLOW:
            route_name = "_next_ledger_dimension_workflow"
            route_fn = lambda: self._next_ledger_dimension_workflow(internal_task=internal_task, history=history)
        elif internal_task.flow_kind is FlowKind.OPENAPI_RESOURCE_WORKFLOW:
            route_name = "_next_openapi_resource_workflow"
            route_fn = lambda: self._next_openapi_resource_workflow(
                internal_task=internal_task,
                task_analysis=task_analysis,
                history=history,
            )

        logger.info(
            "workflow.step.start route=%s method=%s flow_kind=%s target_resource=%s task_family=%s operation=%s search=%s payload=%s history_tail=%s",
            route_name,
            internal_task.method_name,
            internal_task.flow_kind.value,
            internal_task.target_resource,
            task_analysis.task_family,
            task_analysis.operation,
            _trim_payload(internal_task.search),
            _trim_payload(internal_task.payload),
            _history_tail_signature(history),
        )

        if route_fn is None:
            logger.info(
                "workflow.step.no_route method=%s flow_kind=%s target_resource=%s",
                internal_task.method_name,
                internal_task.flow_kind.value,
                internal_task.target_resource,
            )
            return None

        decision = route_fn()
        logger.info(
            "workflow.step.result route=%s method=%s flow_kind=%s decision=%s",
            route_name,
            internal_task.method_name,
            internal_task.flow_kind.value,
            _decision_signature(decision),
        )
        return decision

    def _next_customer_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="customer",
            resource_path="/customer",
            resolver=_resolved_customer_from_internal,
            allowed_fields=(
                "name",
                "organizationNumber",
                "email",
                "invoiceEmail",
                "phoneNumber",
                "phoneNumberMobile",
                "description",
            ),
        )

    def _next_product_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="product",
            resource_path="/product",
            resolver=_resolved_product_from_internal,
            allowed_fields=(
                "name",
                "number",
                "description",
                "orderLineDescription",
                "priceExcludingVatCurrency",
            ),
        )

    def _next_supplier_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="supplier",
            resource_path="/supplier",
            resolver=_resolved_supplier_from_internal,
            allowed_fields=(
                "name",
                "organizationNumber",
                "email",
                "invoiceEmail",
                "phoneNumber",
                "phoneNumberMobile",
                "description",
            ),
        )

    def _next_department_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_simple_upsert(
            internal_task=internal_task,
            history=history,
            resource_name="department",
            resource_path="/department",
            resolver=_resolved_department_from_internal,
            allowed_fields=("name", "departmentNumber"),
        )

    def _next_openapi_resource_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        target_resource = internal_task.target_resource
        if target_resource == "company":
            return self._next_company_workflow(
                internal_task=internal_task,
                history=history,
            )
        if target_resource == "timesheet":
            return self._next_timesheet_workflow(
                internal_task=internal_task,
                history=history,
            )
        return self._next_generic_resource_workflow(
            internal_task=internal_task,
            task_analysis=task_analysis,
            history=history,
        )

    def _next_company_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        desired = _drop_empty(dict(internal_task.payload))
        if not desired:
            return PlannerDecision(
                kind="finish",
                reason="Unable to update company settings because the workflow did not receive any canonical payload fields.",
            )

        if _has_success_exact_where(
            history,
            method="PUT",
            path="/company",
            predicate=lambda request: _request_json_contains(request, desired),
        ):
            return PlannerDecision(kind="finish", reason="The company workflow is complete.")

        if _has_attempt_exact_where(
            history,
            method="PUT",
            path="/company",
            predicate=lambda request: _request_json_contains(request, desired),
        ):
            return None

        return _action(
            reason="Update the company settings using the canonical company endpoint.",
            method="PUT",
            path="/company",
            json=desired,
        )

    def _next_generic_resource_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if not hasattr(self.registry, "resource_capability"):
            return PlannerDecision(
                kind="finish",
                reason=(
                    "Unable to execute the deterministic wrapper workflow because the OpenAPI resource capability "
                    "map is unavailable."
                ),
            )
        capability = self.registry.resource_capability(internal_task.target_resource)
        desired = _drop_empty(dict(internal_task.payload))
        search_params = _generic_search_params(capability, internal_task.search)
        identity_ref = _generic_identity_ref(internal_task.search, desired)

        if internal_task.operation == "reverse":
            return self._next_generic_reverse_workflow(
                internal_task=internal_task,
                capability=capability,
                history=history,
                identity_ref=identity_ref,
                search_params=search_params,
            )

        if internal_task.operation == "search" and not search_params:
            return PlannerDecision(
                kind="finish",
                reason=(
                    "Unable to execute a deterministic search because the workflow did not receive any "
                    f"supported lookup parameters for {internal_task.target_resource}."
                ),
            )

        entity = _resolved_resource_entity(
            history,
            resource_family=internal_task.target_resource,
            collection_path=capability.collection_path,
            detail_path=capability.detail_path,
            ref=identity_ref,
        )

        if entity is None and search_params:
            search_path = capability.collection_path
            if search_path is None and capability.detail_path is not None and search_params.get("id") not in {None, ""}:
                rendered_path = _render_detail_path(capability.detail_path, search_params.get("id"))
                if rendered_path is not None and not _has_attempt_exact(history, method="GET", path=rendered_path):
                    return _action(
                        reason=f"Resolve the {internal_task.target_resource} before mutating it or creating a duplicate.",
                        method="GET",
                        path=rendered_path,
                    )
            elif search_path is not None and not _has_attempt_exact_where(
                history,
                method="GET",
                path=search_path,
                predicate=lambda request, expected=search_params: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Resolve the {internal_task.target_resource} before mutating it or creating a duplicate.",
                    method="GET",
                    path=search_path,
                    params=search_params,
                )
            entity = _resolved_resource_entity(
                history,
                resource_family=internal_task.target_resource,
                collection_path=capability.collection_path,
                detail_path=capability.detail_path,
                ref=identity_ref,
            )

        if internal_task.operation == "delete":
            if not identity_ref:
                return PlannerDecision(
                    kind="finish",
                    reason=(
                        "Unable to delete the requested resource because the workflow did not receive enough "
                        f"lookup fields for {internal_task.target_resource}."
                    ),
                )
            if entity is None:
                return PlannerDecision(
                    kind="finish",
                    reason=f"The requested {internal_task.target_resource} is already absent or could not be resolved for deletion.",
                )
            delete_path = capability.delete_path
            rendered_delete_path = _render_detail_path(delete_path, entity.get("id")) if delete_path else None
            if rendered_delete_path is None:
                return PlannerDecision(
                    kind="finish",
                    reason=f"Delete is not supported through a deterministic route for {internal_task.target_resource}.",
                )
            if _has_success_exact(history, method="DELETE", path=rendered_delete_path):
                return PlannerDecision(kind="finish", reason=f"The {internal_task.target_resource} delete workflow is complete.")
            if _has_attempt_exact(history, method="DELETE", path=rendered_delete_path):
                return None
            delete_params = _drop_empty({"version": entity.get("version")})
            return _action(
                reason=f"Delete the resolved {internal_task.target_resource} using the canonical detail endpoint.",
                method="DELETE",
                path=rendered_delete_path,
                params=delete_params or None,
            )

        if internal_task.operation == "search" and search_params:
            if entity is not None or _has_success_exact_where(
                history,
                method="GET",
                path=capability.collection_path or "",
                predicate=lambda request, expected=search_params: _request_contains_params(request, expected),
            ):
                return PlannerDecision(
                    kind="finish",
                    reason=f"The deterministic {internal_task.target_resource} lookup workflow is complete.",
                )
            return None

        if entity is None:
            if internal_task.operation == "update":
                return PlannerDecision(
                    kind="finish",
                    reason=f"Unable to resolve the {internal_task.target_resource} that should be updated.",
                )
            if not desired:
                return PlannerDecision(
                    kind="finish",
                    reason=(
                        "Unable to continue the deterministic workflow because no target resource was resolved "
                        f"and no canonical payload was provided for {internal_task.target_resource}."
                    ),
                )
            create_path = capability.create_path or capability.collection_path
            if create_path is None:
                return PlannerDecision(
                    kind="finish",
                    reason=f"Create is not supported through a deterministic route for {internal_task.target_resource}.",
                )
            if _has_success_exact_where(
                history,
                method="POST",
                path=create_path,
                predicate=lambda request, expected=desired: _request_json_contains(request, expected),
            ):
                return PlannerDecision(kind="finish", reason=f"The {internal_task.target_resource} workflow is complete.")
            if _has_attempt_exact_where(
                history,
                method="POST",
                path=create_path,
                predicate=lambda request, expected=desired: _request_json_contains(request, expected),
            ):
                return None
            return _action(
                reason=f"Create the {internal_task.target_resource} using the canonical resource endpoint.",
                method="POST",
                path=create_path,
                json=desired,
            )

        if not desired:
            return PlannerDecision(
                kind="finish",
                reason=f"The deterministic {internal_task.target_resource} workflow is complete.",
            )

        if _entity_matches(entity, desired):
            return PlannerDecision(
                kind="finish",
                reason=f"The resolved {internal_task.target_resource} already satisfies the requested state.",
            )

        update_path = capability.update_path or capability.detail_path or capability.collection_path
        rendered_update_path = _render_detail_path(update_path, entity.get("id")) if update_path else None
        if rendered_update_path is None and update_path == capability.collection_path:
            rendered_update_path = update_path
        if rendered_update_path is None:
            return PlannerDecision(
                kind="finish",
                reason=f"Update is not supported through a deterministic route for {internal_task.target_resource}.",
            )

        if capability.detail_path is not None and entity.get("version") in {None, ""} and rendered_update_path != capability.collection_path:
            detail_path = _render_detail_path(capability.detail_path, entity.get("id"))
            if detail_path is not None and not _has_attempt_exact(history, method="GET", path=detail_path):
                return _action(
                    reason=f"Fetch the {internal_task.target_resource} detail record with version information before updating it.",
                    method="GET",
                    path=detail_path,
                )

        update_payload = _build_update_payload(
            entity,
            desired,
            allowed_fields=tuple(sorted(desired.keys())),
        )
        if _has_success_exact_where(
            history,
            method="PUT",
            path=rendered_update_path,
            predicate=lambda request, expected=update_payload: _request_json_contains(request, expected),
        ):
            return PlannerDecision(kind="finish", reason=f"The {internal_task.target_resource} workflow is complete.")
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=rendered_update_path,
            predicate=lambda request, expected=update_payload: _request_json_contains(request, expected),
        ):
            return None
        return _action(
            reason=f"Update the resolved {internal_task.target_resource} to the requested state.",
            method="PUT",
            path=rendered_update_path,
            json=update_payload,
        )

    def _next_generic_reverse_workflow(
        self,
        *,
        internal_task: InternalTask,
        capability: ResourceCapability,
        history: list[dict[str, Any]],
        identity_ref: dict[str, Any],
        search_params: dict[str, Any],
    ) -> PlannerDecision | None:
        if not capability.reverse_paths:
            return PlannerDecision(
                kind="finish",
                reason=f"Reverse is not supported through a deterministic route for {internal_task.target_resource}.",
            )

        entity = _resolved_resource_entity(
            history,
            resource_family=internal_task.target_resource,
            collection_path=capability.collection_path,
            detail_path=capability.detail_path,
            ref=identity_ref,
        )
        if entity is None:
            if capability.collection_path and search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path=capability.collection_path,
                predicate=lambda request, expected=search_params: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Resolve the {internal_task.target_resource} before reversing it.",
                    method="GET",
                    path=capability.collection_path,
                    params=search_params,
                )
            return PlannerDecision(
                kind="finish",
                reason=f"Unable to resolve the {internal_task.target_resource} that should be reversed.",
            )

        entity_id = entity.get("id")
        reverse_path = _render_detail_path(capability.reverse_paths[0], entity_id)
        if reverse_path is None:
            return PlannerDecision(
                kind="finish",
                reason=f"Reverse is not supported through a deterministic route for {internal_task.target_resource}.",
            )
        reverse_params = _drop_empty(
            {
                "date": internal_task.payload.get("date")
                or internal_task.payload.get("reversalDate")
                or internal_task.search.get("date"),
            }
        )
        if _has_success_exact_where(
            history,
            method="PUT",
            path=reverse_path,
            predicate=lambda request, expected=reverse_params: _request_contains_params(request, expected),
        ):
            return PlannerDecision(kind="finish", reason=f"The {internal_task.target_resource} reverse workflow is complete.")
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=reverse_path,
            predicate=lambda request, expected=reverse_params: _request_contains_params(request, expected),
        ):
            return None
        return _action(
            reason=f"Reverse the resolved {internal_task.target_resource} using the canonical Tripletex reverse action.",
            method="PUT",
            path=reverse_path,
            params=reverse_params or None,
        )

    def _next_timesheet_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        merged = _drop_empty({**dict(internal_task.search), **dict(internal_task.payload)})
        employee_ref = _drop_empty(
            {
                "email": merged.get("employeeEmail") or merged.get("email"),
                "firstName": merged.get("employeeFirstName") or merged.get("firstName"),
                "lastName": merged.get("employeeLastName") or merged.get("lastName"),
                "employeeNumber": merged.get("employeeNumber"),
            }
        )
        project_ref = _drop_empty(
            {
                "name": merged.get("projectName") or merged.get("name"),
                "number": merged.get("projectNumber") or merged.get("number"),
            }
        )
        activity_ref = _drop_empty(
            {
                "name": merged.get("activityName"),
                "number": merged.get("activityNumber"),
            }
        )
        entry_date = merged.get("date")
        hours = merged.get("hours")
        comment = merged.get("comment")

        if entry_date in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to execute the timesheet workflow because the entry date is missing.",
            )

        employee = _resolved_employee_by_ref(history, employee_ref)
        if employee is None:
            employee_search = _drop_empty(
                {
                    "email": employee_ref.get("email"),
                    "firstName": employee_ref.get("firstName"),
                    "lastName": employee_ref.get("lastName"),
                    "employeeNumber": employee_ref.get("employeeNumber"),
                    "count": 10,
                    "fields": "id,version,firstName,lastName,email,employeeNumber",
                }
            )
            if employee_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request, expected=employee_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason="Resolve the employee before registering or deleting timesheet hours.",
                    method="GET",
                    path="/employee",
                    params=employee_search,
                )
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve the employee for the requested timesheet workflow.",
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid employee id for the requested timesheet workflow.",
            )

        project = _resolved_project_by_ref(history, project_ref)
        if project is None:
            project_search = _drop_empty(
                {
                    "name": project_ref.get("name"),
                    "number": project_ref.get("number"),
                    "count": 10,
                    "fields": "id,name,number,isClosed,customer",
                }
            )
            if project_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/project",
                predicate=lambda request, expected=project_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason="Resolve the project before registering or deleting timesheet hours.",
                    method="GET",
                    path="/project",
                    params=project_search,
                )
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve the project for the requested timesheet workflow.",
            )

        project_id = project.get("id")
        if project_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid project id for the requested timesheet workflow.",
            )

        activity = _resolved_activity_by_ref(history, activity_ref)
        if activity is None:
            activity_search = _drop_empty(
                {
                    "name": activity_ref.get("name"),
                    "number": activity_ref.get("number"),
                    "count": 10,
                    "fields": "id,name,number,isChargeable,isProjectActivity",
                }
            )
            if activity_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/activity",
                predicate=lambda request, expected=activity_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason="Resolve the activity before registering or deleting timesheet hours.",
                    method="GET",
                    path="/activity",
                    params=activity_search,
                )

            activity_payload = _drop_empty(
                {
                    "name": activity_ref.get("name"),
                    "number": activity_ref.get("number"),
                    "isProjectActivity": True,
                    "isChargeable": True,
                }
            )
            if activity_payload and not _has_attempt_exact_where(
                history,
                method="POST",
                path="/activity",
                predicate=lambda request, expected=activity_payload: _request_json_contains(request, expected),
            ):
                return _action(
                    reason="Create the missing activity before registering timesheet hours.",
                    method="POST",
                    path="/activity",
                    json=activity_payload,
                )
            if activity_payload:
                return PlannerDecision(
                    kind="finish",
                    reason="Unable to resolve the activity for the requested timesheet workflow.",
                )

        if activity is None:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve the activity for the requested timesheet workflow.",
            )

        activity_id = activity.get("id")
        if activity_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid activity id for the requested timesheet workflow.",
            )

        timesheet_search = {
            "employeeId": employee_id,
            "projectId": project_id,
            "activityId": activity_id,
            "dateFrom": entry_date,
            "dateTo": entry_date,
            "count": 10,
            "fields": "id,version,date,hours,projectChargeableHours,comment,chargeable,employee(id),project(id),activity(id)",
        }
        timesheet_entry = _resolved_timesheet_entry_from_history(
            history,
            employee_id=employee_id,
            project_id=project_id,
            activity_id=activity_id,
            entry_date=str(entry_date),
        )
        if timesheet_entry is None:
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/timesheet/entry",
                predicate=lambda request, expected=timesheet_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason="Search for an existing timesheet entry before creating, updating, or deleting it.",
                    method="GET",
                    path="/timesheet/entry",
                    params=timesheet_search,
                )
            if internal_task.operation == "delete":
                return PlannerDecision(
                    kind="finish",
                    reason="The requested timesheet entry is already absent.",
                )
            if hours in {None, ""}:
                return PlannerDecision(
                    kind="finish",
                    reason="Unable to register timesheet hours because the canonical hour amount is missing.",
                )
            create_entry_payload = _build_timesheet_entry_payload(
                employee_id=employee_id,
                project_id=project_id,
                activity_id=activity_id,
                entry_date=str(entry_date),
                hours=hours,
                hourly_rate=merged.get("hourlyRate") or 0,
                comment=comment,
            )
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/timesheet/entry",
                predicate=lambda request, expected=create_entry_payload: _request_json_contains(request, expected),
            ):
                return None
            return _action(
                reason="Register the requested timesheet entry on the resolved employee, project, and activity.",
                method="POST",
                path="/timesheet/entry",
                json=create_entry_payload,
            )

        entry_id = timesheet_entry.get("id")
        if entry_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid timesheet entry id for the requested workflow.",
            )

        if internal_task.operation == "delete":
            if timesheet_entry.get("version") in {None, ""} and not _has_attempt_exact(
                history,
                method="GET",
                path=f"/timesheet/entry/{entry_id}",
            ):
                return _action(
                    reason="Fetch the timesheet entry detail with version information before deleting it.",
                    method="GET",
                    path=f"/timesheet/entry/{entry_id}",
                )
            delete_params = _drop_empty({"version": timesheet_entry.get("version")})
            if _has_success_exact(history, method="DELETE", path=f"/timesheet/entry/{entry_id}"):
                return PlannerDecision(kind="finish", reason="The timesheet delete workflow is complete.")
            if _has_attempt_exact(history, method="DELETE", path=f"/timesheet/entry/{entry_id}"):
                return None
            return _action(
                reason="Delete the resolved timesheet entry using the canonical detail endpoint.",
                method="DELETE",
                path=f"/timesheet/entry/{entry_id}",
                params=delete_params or None,
            )

        if hours in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to register or update timesheet hours because the canonical hour amount is missing.",
            )

        if not _timesheet_entry_matches(
            timesheet_entry,
            entry_date=str(entry_date),
            hours=hours,
            hourly_rate=merged.get("hourlyRate") or 0,
            comment=comment,
        ):
            if timesheet_entry.get("version") in {None, ""} and not _has_attempt_exact(
                history,
                method="GET",
                path=f"/timesheet/entry/{entry_id}",
            ):
                return _action(
                    reason="Fetch the timesheet entry detail with version information before updating it.",
                    method="GET",
                    path=f"/timesheet/entry/{entry_id}",
                )
            update_entry_payload = _build_timesheet_entry_payload(
                employee_id=employee_id,
                project_id=project_id,
                activity_id=activity_id,
                entry_date=str(entry_date),
                hours=hours,
                hourly_rate=merged.get("hourlyRate") or 0,
                comment=comment,
                entry_id=entry_id,
                entry_version=timesheet_entry.get("version"),
            )
            if _has_attempt_exact_where(
                history,
                method="PUT",
                path=f"/timesheet/entry/{entry_id}",
                predicate=lambda request, expected=update_entry_payload: _request_json_contains(request, expected),
            ):
                return None
            return _action(
                reason="Update the resolved timesheet entry to the requested state.",
                method="PUT",
                path=f"/timesheet/entry/{entry_id}",
                json=update_entry_payload,
            )

        return PlannerDecision(kind="finish", reason="The timesheet workflow is complete.")

    def _next_employee_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        return self._next_employee_onboarding_workflow(
            internal_task=internal_task,
            history=history,
        )

    def _next_employee_onboarding_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        payload = dict(internal_task.payload)
        department_ref = dict(payload.pop("departmentRef", {}) or {})
        employment = dict(payload.pop("employment", {}) or {})

        department = _resolved_department_by_ref(history, department_ref)
        if department_ref and department is None:
            search_params = _drop_empty(dict(department_ref))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/department",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the employee department before creating or updating the employee.",
                    method="GET",
                    path="/department",
                    params=search_params,
                )

            department_payload = _department_payload_from_ref(department_ref)
            if department_payload and not _has_attempt_exact_where(
                history,
                method="POST",
                path="/department",
                predicate=lambda request: _request_json_contains(request, department_payload),
            ):
                return _action(
                    reason="Create the employee department because the onboarding workflow did not find an existing match.",
                    method="POST",
                    path="/department",
                    json=department_payload,
                )
            return None

        desired_employee = dict(payload)
        if department is not None and department.get("id") not in {None, ""}:
            desired_employee["department"] = {"id": department["id"]}

        employee = _resolved_employee_by_ref(history, internal_task.search or desired_employee)
        if employee is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the employee before creating a duplicate profile during onboarding.",
                    method="GET",
                    path="/employee",
                    params=search_params,
                )

            if not desired_employee.get("firstName") or not desired_employee.get("lastName"):
                return None

            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/employee",
                predicate=lambda request: _request_json_contains(request, desired_employee),
            ):
                return None

            return _action(
                reason="Create the employee base profile with the resolved identity and department fields.",
                method="POST",
                path="/employee",
                json=desired_employee,
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return None

        if not _entity_matches(employee, desired_employee):
            if employee.get("version") in {None, ""} and not _has_attempt_exact(history, method="GET", path=f"/employee/{employee_id}"):
                return _action(
                    reason="Fetch the employee record with version information before updating onboarding fields.",
                    method="GET",
                    path=f"/employee/{employee_id}",
                )

            update_payload = _build_update_payload(
                employee,
                desired_employee,
                allowed_fields=(
                    "firstName",
                    "lastName",
                    "email",
                    "employeeNumber",
                    "dateOfBirth",
                    "nationalIdentityNumber",
                    "bankAccountNumber",
                    "phoneNumberMobile",
                    "phoneNumberWork",
                    "comments",
                    "userType",
                    "department",
                ),
            )
            if _has_attempt_exact_where(
                history,
                method="PUT",
                path=f"/employee/{employee_id}",
                predicate=lambda request: _request_json_contains(request, update_payload),
            ):
                return None
            return _action(
                reason="Update the employee base profile to the requested onboarding state.",
                method="PUT",
                path=f"/employee/{employee_id}",
                json=update_payload,
            )

        if not employment:
            return PlannerDecision(kind="finish", reason="The employee onboarding workflow is complete.")

        employment_record = _resolved_employment_for_employee(history, employee_id=employee_id)
        if employment_record is None:
            employment_search = {
                "employeeId": employee_id,
                "count": 20,
                "fields": "id,version,startDate,endDate,employee(id),employmentDetails",
            }
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee/employment",
                predicate=lambda request: _request_contains_params(request, employment_search),
            ):
                return _action(
                    reason="Resolve the employee employment record before creating a new employment.",
                    method="GET",
                    path="/employee/employment",
                    params=employment_search,
                )

            create_employment_payload = _drop_empty(
                {
                    "employee": {"id": employee_id},
                    "startDate": employment.get("startDate") or date.today().isoformat(),
                }
            )
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/employee/employment",
                predicate=lambda request: _request_json_contains(request, create_employment_payload),
            ):
                return None
            return _action(
                reason="Create the employment record for the employee before adding employment details.",
                method="POST",
                path="/employee/employment",
                json=create_employment_payload,
            )

        employment_id = employment_record.get("id")
        if employment_id in {None, ""}:
            return None

        desired_employment = _drop_empty(
            {
                "employee": {"id": employee_id},
                "startDate": employment.get("startDate") or employment_record.get("startDate"),
                "endDate": employment.get("endDate"),
            }
        )
        if desired_employment and not _entity_matches(employment_record, desired_employment):
            if employment_record.get("version") in {None, ""} and not _has_attempt_exact(
                history,
                method="GET",
                path=f"/employee/employment/{employment_id}",
            ):
                return _action(
                    reason="Fetch the employment record with version information before updating start or end dates.",
                    method="GET",
                    path=f"/employee/employment/{employment_id}",
                )

            update_employment_payload = _build_update_payload(
                employment_record,
                desired_employment,
                allowed_fields=("employee", "startDate", "endDate"),
            )
            if _has_attempt_exact_where(
                history,
                method="PUT",
                path=f"/employee/employment/{employment_id}",
                predicate=lambda request: _request_json_contains(request, update_employment_payload),
            ):
                return None
            return _action(
                reason="Update the employment record to the requested onboarding dates.",
                method="PUT",
                path=f"/employee/employment/{employment_id}",
                json=update_employment_payload,
            )

        desired_details = _drop_empty(
            {
                "employment": {"id": employment_id},
                "date": employment.get("startDate") or employment_record.get("startDate") or date.today().isoformat(),
                "employmentForm": employment.get("employmentForm"),
                "remunerationType": employment.get("remunerationType"),
                "percentageOfFullTimeEquivalent": employment.get("percentageOfFullTimeEquivalent"),
                "annualSalary": employment.get("annualSalary"),
                "hourlyWage": employment.get("hourlyWage"),
            }
        )

        occupation_code_ref = employment.get("occupationCodeRef")
        if occupation_code_ref:
            occupation_code = _resolved_occupation_code_by_ref(history, occupation_code_ref)
            if occupation_code is None:
                occupation_id = (occupation_code_ref or {}).get("id")
                if occupation_id not in {None, ""} and not _has_attempt_exact(
                    history,
                    method="GET",
                    path=f"/employee/employment/occupationCode/{occupation_id}",
                ):
                    return _action(
                        reason="Resolve the occupation code by id before creating employment details.",
                        method="GET",
                        path=f"/employee/employment/occupationCode/{occupation_id}",
                        params={"fields": "id,nameNO,code"},
                    )

                occupation_search = _drop_empty(
                    {
                        "code": (occupation_code_ref or {}).get("code"),
                        "nameNO": (occupation_code_ref or {}).get("nameNO"),
                        "count": 20,
                        "fields": "id,nameNO,code",
                    }
                )
                if occupation_search and not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/employee/employment/occupationCode",
                    predicate=lambda request: _request_contains_params(request, occupation_search),
                ):
                    return _action(
                        reason="Resolve the occupation code before creating employment details.",
                        method="GET",
                        path="/employee/employment/occupationCode",
                        params=occupation_search,
                    )
                fallback_occupation = _drop_empty(
                    {
                        "code": (occupation_code_ref or {}).get("code"),
                        "nameNO": (occupation_code_ref or {}).get("nameNO"),
                    }
                )
                if fallback_occupation:
                    desired_details["occupationCode"] = fallback_occupation
                else:
                    return None

            if occupation_code is not None and occupation_code.get("id") not in {None, ""}:
                desired_details["occupationCode"] = {"id": occupation_code["id"]}
            elif "occupationCode" not in desired_details:
                fallback_occupation = _drop_empty(
                    {
                        "code": (occupation_code_ref or {}).get("code"),
                        "nameNO": (occupation_code_ref or {}).get("nameNO"),
                    }
                )
                if fallback_occupation:
                    desired_details["occupationCode"] = fallback_occupation

        if len(desired_details) <= 1:
            return PlannerDecision(kind="finish", reason="The employee onboarding workflow is complete.")

        details_record = _resolved_employment_details_for_employment(history, employment_id=employment_id)
        if details_record is None:
            details_search = {
                "employmentId": str(employment_id),
                "count": 20,
                "fields": "id,version,date,employment(id),employmentForm,remunerationType,occupationCode,percentageOfFullTimeEquivalent,annualSalary,hourlyWage",
            }
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee/employment/details",
                predicate=lambda request: _request_contains_params(request, details_search),
            ):
                return _action(
                    reason="Resolve existing employment details before creating a new details record.",
                    method="GET",
                    path="/employee/employment/details",
                    params=details_search,
                )

            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/employee/employment/details",
                predicate=lambda request: _request_json_contains(request, desired_details),
            ):
                return None
            return _action(
                reason="Create employment details with the requested onboarding fields.",
                method="POST",
                path="/employee/employment/details",
                json=desired_details,
            )

        details_id = details_record.get("id")
        if details_id in {None, ""}:
            return None

        if _entity_matches(details_record, desired_details):
            return PlannerDecision(kind="finish", reason="The employee onboarding workflow is complete.")

        if details_record.get("version") in {None, ""} and not _has_attempt_exact(
            history,
            method="GET",
            path=f"/employee/employment/details/{details_id}",
        ):
            return _action(
                reason="Fetch the employment details record with version information before updating it.",
                method="GET",
                path=f"/employee/employment/details/{details_id}",
                params={"fields": "id,version,date,employment(id),employmentForm,remunerationType,occupationCode,percentageOfFullTimeEquivalent,annualSalary,hourlyWage"},
            )

        update_details_payload = _build_update_payload(
            details_record,
            desired_details,
            allowed_fields=(
                "employment",
                "date",
                "employmentType",
                "employmentForm",
                "remunerationType",
                "workingHoursScheme",
                "shiftDurationHours",
                "occupationCode",
                "percentageOfFullTimeEquivalent",
                "annualSalary",
                "hourlyWage",
            ),
        )
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"/employee/employment/details/{details_id}",
            predicate=lambda request: _request_json_contains(request, update_details_payload),
        ):
            return None
        return _action(
            reason="Update the employment details to the requested onboarding state.",
            method="PUT",
            path=f"/employee/employment/details/{details_id}",
            json=update_details_payload,
        )

    def _next_travel_expense_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if internal_task.operation == "delete":
            return self._next_delete_travel_expense_workflow(
                internal_task=internal_task,
                history=history,
            )

        employee = _resolved_employee_from_internal(history, internal_task)
        if employee is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the employee before creating the travel expense.",
                    method="GET",
                    path="/employee",
                    params=search_params,
                )
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve the employee for the requested travel expense.",
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid employee id for the requested travel expense.",
            )

        payload = dict(internal_task.payload)
        payment_type_id: Any | None = None
        costs = [item for item in (payload.get("costs") or []) if isinstance(item, dict)]
        if costs:
            payment_type = _resolved_travel_payment_type_from_history(history)
            payment_type_search = {
                "showOnEmployeeExpenses": True,
                "count": 20,
                "fields": "id,description,displayName,showOnEmployeeExpenses",
            }
            if payment_type is None:
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/travelExpense/paymentType",
                    predicate=lambda request: _request_contains_params(request, payment_type_search),
                ):
                    return _action(
                        reason="Resolve an employee-expense payment type before creating the travel expense costs.",
                        method="GET",
                        path="/travelExpense/paymentType",
                        params=payment_type_search,
                    )
                return PlannerDecision(
                    kind="finish",
                    reason="Unable to resolve an employee-expense payment type for the requested travel expense.",
                )
            payment_type_id = payment_type.get("id")
            if payment_type_id in {None, ""}:
                return PlannerDecision(
                    kind="finish",
                    reason="Unable to resolve a valid payment type id for the requested travel expense.",
                )

        resolved_cost_categories: list[dict[str, Any]] = []
        for cost in costs:
            description = cost.get("description")
            if _is_blank(description):
                return PlannerDecision(
                    kind="finish",
                    reason="Unable to create a travel expense cost without a description.",
                )
            search_params = _travel_expense_cost_category_search_params(description)
            category = _resolved_travel_cost_category_from_history(
                history,
                query=search_params.get("query"),
                description=description,
            )
            if category is None:
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/travelExpense/costCategory",
                    predicate=lambda request: _request_contains_params(request, search_params),
                ):
                    return _action(
                        reason=f"Resolve a travel expense cost category for '{description}'.",
                        method="GET",
                        path="/travelExpense/costCategory",
                        params=search_params,
                    )
                return PlannerDecision(
                    kind="finish",
                    reason=f"Unable to resolve a travel expense cost category for '{description}'.",
                )
            resolved_cost_categories.append(category)

        create_payload = _build_travel_expense_payload(
            internal_task=internal_task,
            employee_id=employee_id,
            payment_type_id=payment_type_id,
            resolved_cost_categories=resolved_cost_categories,
        )
        if create_payload is None:
            return PlannerDecision(
                kind="finish",
                reason="Unable to build a valid travel expense payload from the provided request.",
            )

        if _has_success_exact_where(
            history,
            method="POST",
            path="/travelExpense",
            predicate=lambda request: _request_json_contains(request, create_payload),
        ):
            return PlannerDecision(kind="finish", reason="The travel expense workflow is complete.")

        if _has_attempt_exact_where(
            history,
            method="POST",
            path="/travelExpense",
            predicate=lambda request: _request_json_contains(request, create_payload),
        ):
            return None

        return _action(
            reason="Create the travel expense with the resolved employee, travel details, per diem, and reimbursable costs.",
            method="POST",
            path="/travelExpense",
            json=create_payload,
        )

    def _next_delete_travel_expense_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        employee = _resolved_employee_from_internal(history, internal_task)
        if employee is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the employee before locating the travel expense to delete.",
                    method="GET",
                    path="/employee",
                    params=search_params,
                )
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve the employee for the requested travel expense deletion.",
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid employee id for the requested travel expense deletion.",
            )

        travel_expense = _resolved_travel_expense_from_history(
            history,
            employee_id=employee_id,
            internal_task=internal_task,
        )
        if travel_expense is None:
            search_params = _travel_expense_lookup_params(employee_id=employee_id, internal_task=internal_task)
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/travelExpense",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Locate the travel expense before deleting it.",
                    method="GET",
                    path="/travelExpense",
                    params=search_params,
                )
            return PlannerDecision(
                kind="finish",
                reason="Unable to locate a matching travel expense to delete.",
            )

        travel_expense_id = travel_expense.get("id")
        if travel_expense_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid travel expense id for deletion.",
            )

        if _has_success_exact(history, method="DELETE", path=f"/travelExpense/{travel_expense_id}"):
            return PlannerDecision(kind="finish", reason="The travel expense delete workflow is complete.")

        if _has_attempt_exact(history, method="DELETE", path=f"/travelExpense/{travel_expense_id}"):
            return None

        return _action(
            reason="Delete the resolved travel expense using the canonical Tripletex delete endpoint.",
            method="DELETE",
            path=f"/travelExpense/{travel_expense_id}",
        )

    def _next_month_end_closing_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        voucher_date = internal_task.payload.get("voucherDate") or date.today().isoformat()
        voucher_specs = [item for item in (internal_task.payload.get("vouchers") or []) if isinstance(item, dict)]
        if not voucher_specs:
            return PlannerDecision(
                kind="finish",
                reason="Unable to derive any month-end closing vouchers from the request.",
            )

        for voucher_spec in voucher_specs:
            unresolved_account = _first_unresolved_month_end_account_number(history, voucher_spec=voucher_spec)
            if unresolved_account is not None:
                search_params = {
                    "number": unresolved_account,
                    "count": 10,
                    "fields": "id,number,name",
                }
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/ledger/account",
                    predicate=lambda request: _request_contains_params(request, search_params),
                ):
                    return _action(
                        reason=f"Resolve ledger account {unresolved_account} before creating the month-end voucher.",
                        method="GET",
                        path="/ledger/account",
                        params=search_params,
                    )
                return PlannerDecision(
                    kind="finish",
                    reason=f"Unable to resolve ledger account {unresolved_account} required for month-end closing.",
                )

            create_payload = _build_month_end_voucher_payload(
                voucher_date=voucher_date,
                voucher_spec=voucher_spec,
                history=history,
            )
            if create_payload is None:
                return PlannerDecision(
                    kind="finish",
                    reason="Unable to build a valid month-end voucher payload from the resolved ledger accounts.",
                )

            if _has_success_exact_where(
                history,
                method="POST",
                path="/ledger/voucher",
                predicate=lambda request: _request_json_contains(request, create_payload),
            ):
                continue

            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/ledger/voucher",
                predicate=lambda request: _request_json_contains(request, create_payload),
            ):
                return None

            return _action(
                reason=f"Create the month-end voucher '{voucher_spec.get('key') or voucher_spec.get('description') or 'voucher'}'.",
                method="POST",
                path="/ledger/voucher",
                json=create_payload,
            )

        return PlannerDecision(kind="finish", reason="The month-end closing workflow is complete.")

    def _next_expense_increase_project_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        payload = dict(internal_task.payload)
        baseline_period = dict(payload.get("baselinePeriod") or {})
        comparison_period = dict(payload.get("comparisonPeriod") or {})
        top_count = int(payload.get("topCount") or 3)
        create_activity = bool(payload.get("createActivity"))
        is_internal = bool(payload.get("isInternal"))

        for label, period in (("baseline", baseline_period), ("comparison", comparison_period)):
            search_params = _expense_increase_posting_search_params(period)
            if search_params is None:
                return PlannerDecision(
                    kind="finish",
                    reason=f"Unable to derive the {label} ledger period required for expense-increase analysis.",
                )
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/posting",
                predicate=lambda request, expected=search_params: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Load ledger postings for the {label} comparison period before creating projects.",
                    method="GET",
                    path="/ledger/posting",
                    params=search_params,
                )

        top_accounts = _resolved_top_expense_increase_accounts(history, internal_task=internal_task, top_count=top_count)
        if not top_accounts:
            return PlannerDecision(
                kind="finish",
                reason="Unable to identify any expense accounts with a positive increase between the requested periods.",
            )

        for account in top_accounts:
            project_ref = {"name": account["name"]}
            project = _resolved_project_by_ref(history, project_ref)
            project_search = {"name": account["name"], "count": 10}
            if project is None:
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/project",
                    predicate=lambda request, expected=project_search: _request_contains_params(request, expected),
                ):
                    return _action(
                        reason=f"Resolve whether the internal project '{account['name']}' already exists.",
                        method="GET",
                        path="/project",
                        params=project_search,
                    )
                project_payload = _drop_empty({"name": account["name"], "isInternal": is_internal or None})
                if not _has_attempt_exact_where(
                    history,
                    method="POST",
                    path="/project",
                    predicate=lambda request, expected=project_payload: _request_json_contains(request, expected),
                ):
                    return _action(
                        reason=f"Create the internal project for expense account '{account['name']}'.",
                        method="POST",
                        path="/project",
                        json=project_payload,
                    )
                return None

            if not create_activity:
                continue

            activity_ref = {"name": account["name"]}
            activity = _resolved_activity_by_ref(history, activity_ref)
            activity_search = {"name": account["name"], "count": 10}
            if activity is None:
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/activity",
                    predicate=lambda request, expected=activity_search: _request_contains_params(request, expected),
                ):
                    return _action(
                        reason=f"Resolve whether the activity '{account['name']}' already exists.",
                        method="GET",
                        path="/activity",
                        params=activity_search,
                    )
                activity_payload = {
                    "name": account["name"],
                    "isProjectActivity": True,
                    "isChargeable": False,
                }
                if not _has_attempt_exact_where(
                    history,
                    method="POST",
                    path="/activity",
                    predicate=lambda request, expected=activity_payload: _request_json_contains(request, expected),
                ):
                    return _action(
                        reason=f"Create the activity for expense account '{account['name']}'.",
                        method="POST",
                        path="/activity",
                        json=activity_payload,
                    )
                return None

        return PlannerDecision(kind="finish", reason="The expense-increase project workflow is complete.")

    def _next_salary_payroll_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if _has_success_exact(history, method="POST", path="/salary/transaction"):
            return PlannerDecision(kind="finish", reason="The salary payroll workflow is complete.")

        employee = _resolved_employee_from_internal(history, internal_task)
        if employee is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the employee before creating the salary transaction.",
                    method="GET",
                    path="/employee",
                    params=search_params,
                )
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve the employee for the requested payroll workflow.",
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason="Unable to resolve a valid employee id for the payroll workflow.",
            )

        salary_lines = [line for line in (internal_task.payload.get("salaryLines") or []) if isinstance(line, dict)]
        if not salary_lines:
            return PlannerDecision(
                kind="finish",
                reason="Unable to build any salary lines for the payroll workflow.",
            )

        resolved_salary_types: list[dict[str, Any]] = []
        for line in salary_lines:
            salary_type_ref = _salary_line_type_ref(line)
            salary_type = _resolved_salary_type_by_ref(history, salary_type_ref)
            if salary_type is None:
                search_params = _salary_type_search_params(salary_type_ref)
                if not search_params:
                    return PlannerDecision(
                        kind="finish",
                        reason="Unable to resolve a salary type because the structured payroll line is missing a searchable salary-type reference.",
                    )
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/salary/type",
                    predicate=lambda request, expected=search_params: _request_contains_params(request, expected),
                ):
                    return _action(
                        reason="Resolve the salary type before creating the salary transaction.",
                        method="GET",
                        path="/salary/type",
                        params=search_params,
                    )
                return PlannerDecision(
                    kind="finish",
                    reason="Unable to resolve one or more salary types required for the payroll workflow.",
                )
            resolved_salary_types.append(salary_type)

        create_payload = _build_salary_transaction_payload(
            internal_task=internal_task,
            employee_id=employee_id,
            salary_types=resolved_salary_types,
        )
        if create_payload is None:
            return PlannerDecision(
                kind="finish",
                reason="Unable to build a valid salary-transaction payload from the structured payroll workflow.",
            )

        create_params = _drop_empty(
            {
                "generateTaxDeduction": internal_task.payload.get("generateTaxDeduction"),
            }
        )

        if _has_attempt_exact_where(
            history,
            method="POST",
            path="/salary/transaction",
            predicate=lambda request, expected_params=create_params, expected_json=create_payload: _request_contains_params(request, expected_params)
            and _request_json_contains(request, expected_json),
        ):
            return None

        return _action(
            reason="Create the salary transaction with the resolved employee and salary types.",
            method="POST",
            path="/salary/transaction",
            params=create_params,
            json=create_payload,
        )

    def _next_bank_reconciliation_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        statement_entries = [entry for entry in (internal_task.payload.get("statementEntries") or []) if isinstance(entry, dict)]
        if not statement_entries:
            return PlannerDecision(
                kind="finish",
                reason="Unable to continue bank reconciliation because the workflow did not receive any structured statement entries.",
            )

        for entry in statement_entries:
            direction = _bank_statement_direction(entry)
            if direction == "outgoing":
                decision = self._next_bank_supplier_payment_entry(
                    internal_task=internal_task,
                    task_analysis=task_analysis,
                    history=history,
                    entry=entry,
                )
            else:
                decision = self._next_bank_customer_payment_entry(
                    internal_task=internal_task,
                    task_analysis=task_analysis,
                    history=history,
                    entry=entry,
                )
            if decision is None:
                return None
            if decision.kind != "finish":
                return decision
            if _finish_reason_indicates_failure(decision.reason):
                return decision

        return PlannerDecision(kind="finish", reason="The bank reconciliation workflow is complete.")

    def _next_bank_customer_payment_entry(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
        entry: dict[str, Any],
    ) -> PlannerDecision | None:
        customer_ref = dict(entry.get("customer") or {})
        customer = _resolved_customer_by_ref(history, customer_ref)
        customer_id = customer.get("id") if isinstance(customer, dict) else None
        if customer_id in {None, ""} and customer_ref:
            customer_search = _drop_empty(
                {
                    "organizationNumber": customer_ref.get("organizationNumber"),
                    "customerName": customer_ref.get("customerName") or customer_ref.get("name"),
                    "email": customer_ref.get("email"),
                    "count": 10,
                }
            )
            if customer_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request, expected=customer_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Resolve the customer for bank statement entry {entry.get('entryId') or 'entry'}.",
                    method="GET",
                    path="/customer",
                    params=customer_search,
                )
            customer = _resolved_customer_by_ref(history, customer_ref)
            customer_id = customer.get("id") if isinstance(customer, dict) else None

        invoice = _resolved_bank_customer_invoice_from_history(
            history,
            entry=entry,
            customer_id=customer_id,
        )
        if invoice is None:
            invoice_search = _bank_customer_invoice_search_params(
                entry=entry,
                customer_id=customer_id,
                internal_task=internal_task,
                task_analysis=task_analysis,
            )
            if invoice_search is None:
                return PlannerDecision(
                    kind="finish",
                    reason=f"Unable to search for an outgoing invoice for bank statement entry {entry.get('entryId') or 'entry'}.",
                )
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice",
                predicate=lambda request, expected=invoice_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Locate the outgoing invoice for bank statement entry {entry.get('entryId') or 'entry'}.",
                    method="GET",
                    path="/invoice",
                    params=invoice_search,
                )
            return PlannerDecision(
                kind="finish",
                reason=f"Unable to resolve a matching outgoing invoice for bank statement entry {entry.get('entryId') or 'entry'}.",
            )

        invoice_id = invoice.get("id")
        if invoice_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason=f"Unable to resolve a valid outgoing invoice id for bank statement entry {entry.get('entryId') or 'entry'}.",
            )

        payment_type_id = _fallback_first_payment_type_id(history)
        if payment_type_id in {None, ""}:
            payment_type_params = {"count": 10}
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice/paymentType",
                predicate=lambda request, expected=payment_type_params: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Resolve an outgoing invoice payment type for bank statement entry {entry.get('entryId') or 'entry'}.",
                    method="GET",
                    path="/invoice/paymentType",
                    params=payment_type_params,
                )
            return PlannerDecision(
                kind="finish",
                reason=f"Unable to resolve an outgoing invoice payment type for bank statement entry {entry.get('entryId') or 'entry'}.",
            )

        payment_params = _drop_empty(
            {
                "paymentDate": entry.get("paymentDate"),
                "paymentTypeId": payment_type_id,
                "paidAmount": _bank_entry_paid_amount(entry),
            }
        )
        if _has_success_exact_where(
            history,
            method="PUT",
            path=f"/invoice/{invoice_id}/:payment",
            predicate=lambda request, expected=payment_params: _request_contains_params(request, expected),
        ):
            return PlannerDecision(kind="finish", reason="The current bank customer-payment entry is complete.")

        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"/invoice/{invoice_id}/:payment",
            predicate=lambda request, expected=payment_params: _request_contains_params(request, expected),
        ):
            return None

        return _action(
            reason=f"Register the outgoing-invoice payment for bank statement entry {entry.get('entryId') or 'entry'}.",
            method="PUT",
            path=f"/invoice/{invoice_id}/:payment",
            params=payment_params,
        )

    def _next_bank_supplier_payment_entry(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
        entry: dict[str, Any],
    ) -> PlannerDecision | None:
        supplier_ref = dict(entry.get("supplier") or {})
        supplier = _resolved_supplier_by_ref(history, supplier_ref)
        supplier_id = supplier.get("id") if isinstance(supplier, dict) else None
        if supplier_id in {None, ""} and supplier_ref:
            supplier_search = _drop_empty(
                {
                    "organizationNumber": supplier_ref.get("organizationNumber"),
                    "supplierName": supplier_ref.get("supplierName") or supplier_ref.get("name"),
                    "email": supplier_ref.get("email"),
                    "count": 10,
                    "fields": "id,name,organizationNumber,email,invoiceEmail",
                }
            )
            if supplier_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/supplier",
                predicate=lambda request, expected=supplier_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Resolve the supplier for bank statement entry {entry.get('entryId') or 'entry'}.",
                    method="GET",
                    path="/supplier",
                    params=supplier_search,
                )
            supplier = _resolved_supplier_by_ref(history, supplier_ref)
            supplier_id = supplier.get("id") if isinstance(supplier, dict) else None

        incoming_invoice = _resolved_bank_supplier_invoice_from_history(
            history,
            entry=entry,
            supplier_id=supplier_id,
        )
        if incoming_invoice is None:
            incoming_invoice_search = _bank_supplier_invoice_search_params(
                entry=entry,
                supplier_id=supplier_id,
                internal_task=internal_task,
                task_analysis=task_analysis,
            )
            if incoming_invoice_search is None:
                return PlannerDecision(
                    kind="finish",
                    reason=f"Unable to search for a supplier invoice for bank statement entry {entry.get('entryId') or 'entry'}.",
                )
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/incomingInvoice/search",
                predicate=lambda request, expected=incoming_invoice_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason=f"Locate the supplier invoice for bank statement entry {entry.get('entryId') or 'entry'}.",
                    method="GET",
                    path="/incomingInvoice/search",
                    params=incoming_invoice_search,
                )
            return PlannerDecision(
                kind="finish",
                reason=f"Unable to resolve a matching supplier invoice for bank statement entry {entry.get('entryId') or 'entry'}.",
            )

        voucher_id = incoming_invoice.get("voucherId") or incoming_invoice.get("id")
        if voucher_id in {None, ""}:
            return PlannerDecision(
                kind="finish",
                reason=f"Unable to resolve a valid incoming-invoice voucher id for bank statement entry {entry.get('entryId') or 'entry'}.",
            )

        payment_payload = _drop_empty(
            {
                "amountCurrency": _bank_entry_paid_amount(entry),
                "paymentDate": entry.get("paymentDate"),
                "partialPayment": _bank_supplier_partial_payment(entry, incoming_invoice=incoming_invoice),
                "useDefaultPaymentType": True,
            }
        )
        if _has_success_exact_where(
            history,
            method="POST",
            path=f"/incomingInvoice/{voucher_id}/addPayment",
            predicate=lambda request, expected=payment_payload: _request_json_contains(request, expected),
        ):
            return PlannerDecision(kind="finish", reason="The current bank supplier-payment entry is complete.")

        if _has_attempt_exact_where(
            history,
            method="POST",
            path=f"/incomingInvoice/{voucher_id}/addPayment",
            predicate=lambda request, expected=payment_payload: _request_json_contains(request, expected),
        ):
            return None

        return _action(
            reason=f"Register the supplier-invoice payment for bank statement entry {entry.get('entryId') or 'entry'}.",
            method="POST",
            path=f"/incomingInvoice/{voucher_id}/addPayment",
            json=payment_payload,
        )

    def _next_invoice_payment_reversal_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if _has_success(history, method="PUT", path_suffix="/:reverse"):
            return PlannerDecision(kind="finish", reason="The invoice payment reversal workflow is complete.")

        customer = _resolved_customer_by_ref(history, internal_task.search or internal_task.payload.get("customer"))
        if customer is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the customer before locating the returned payment voucher.",
                    method="GET",
                    path="/customer",
                    params=search_params,
                )
            return None

        customer_id = customer.get("id")
        if customer_id in {None, ""}:
            return None

        invoice = _resolved_credit_note_target_invoice(history, internal_task=internal_task)
        if invoice is None:
            invoice_search = _credit_note_invoice_search_params(
                task_analysis,
                customer_id=customer_id,
                invoice_number=internal_task.payload.get("invoiceNumber"),
            )
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice",
                predicate=lambda request: _request_contains_params(request, invoice_search),
            ):
                return _action(
                    reason="Locate the invoice whose payment should be reversed.",
                    method="GET",
                    path="/invoice",
                    params=invoice_search,
                )
            return None

        posting = _resolved_payment_reversal_posting(history, invoice=invoice, internal_task=internal_task)
        if posting is None:
            posting_search = _payment_reversal_posting_search_params(task_analysis, customer_id=customer_id)
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/posting",
                predicate=lambda request: _request_contains_params(request, posting_search),
            ):
                return _action(
                    reason="Locate the payment posting voucher before reversing the returned invoice payment.",
                    method="GET",
                    path="/ledger/posting",
                    params=posting_search,
                )

            relaxed_posting_search = _payment_reversal_posting_search_params(
                task_analysis,
                customer_id=customer_id,
                include_type=False,
            )
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/posting",
                predicate=lambda request: _request_contains_params(request, relaxed_posting_search),
            ):
                return _action(
                    reason="Retry voucher discovery without a posting-type filter to handle sandbox variance in returned-payment postings.",
                    method="GET",
                    path="/ledger/posting",
                    params=relaxed_posting_search,
                )
            return None

        voucher_id = _entity_id(posting.get("voucher"))
        if voucher_id in {None, ""}:
            return None

        reverse_params = {
            "date": internal_task.payload.get("reversalDate") or default_action_date(task_analysis, "reversalDate", "date"),
        }
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"/ledger/voucher/{voucher_id}/:reverse",
            predicate=lambda request: _request_contains_params(request, reverse_params),
        ):
            return None
        return _action(
            reason="Reverse the voucher tied to the returned invoice payment so the invoice becomes outstanding again.",
            method="PUT",
            path=f"/ledger/voucher/{voucher_id}/:reverse",
            params=reverse_params,
        )

    def _next_project_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        payload = dict(internal_task.payload)
        customer_ref = payload.pop("customerRef", None)
        department_ref = payload.pop("departmentRef", None)
        manager_ref = payload.pop("projectManagerRef", None)

        customer = _resolved_customer_by_ref(history, customer_ref)
        if customer_ref and customer is None:
            customer_task = InternalTask(
                method_name="UpsertCustomer",
                flow_kind=FlowKind.CUSTOMER_UPSERT,
                operation="create",
                target_resource="customer",
                objective=internal_task.objective,
                search=_drop_empty(
                    {
                        "organizationNumber": (customer_ref or {}).get("organizationNumber"),
                        "customerName": (customer_ref or {}).get("customerName") or (customer_ref or {}).get("name"),
                        "email": (customer_ref or {}).get("email"),
                        "count": 10,
                    }
                ),
                payload=_drop_empty(
                    {
                        "name": (customer_ref or {}).get("customerName") or (customer_ref or {}).get("name"),
                        "organizationNumber": (customer_ref or {}).get("organizationNumber"),
                        "email": (customer_ref or {}).get("email"),
                    }
                ),
                notes=internal_task.notes,
            )
            customer_decision = self._next_customer_upsert(internal_task=customer_task, history=history)
            if customer_decision is not None:
                if customer_decision.kind == "finish" and _finish_reason_indicates_failure(customer_decision.reason):
                    return customer_decision
                if customer_decision.kind != "finish":
                    return customer_decision
            customer = _resolved_customer_by_ref(history, customer_ref)
            if customer is None:
                return None

        department = _resolved_department_by_ref(history, department_ref)
        if department_ref and department is None:
            department_task = InternalTask(
                method_name="UpsertDepartment",
                flow_kind=FlowKind.DEPARTMENT_UPSERT,
                operation="create",
                target_resource="department",
                objective=internal_task.objective,
                search=_drop_empty(
                    {
                        "departmentNumber": (department_ref or {}).get("departmentNumber"),
                        "name": (department_ref or {}).get("name"),
                        "count": 10,
                    }
                ),
                payload=_department_payload_from_ref(department_ref) or {},
                notes=internal_task.notes,
            )
            department_decision = self._next_department_upsert(internal_task=department_task, history=history)
            if department_decision is not None:
                if department_decision.kind == "finish" and _finish_reason_indicates_failure(department_decision.reason):
                    return department_decision
                if department_decision.kind != "finish":
                    return department_decision
            department = _resolved_department_by_ref(history, department_ref)
            if department is None:
                return None

        manager = _resolved_employee_by_ref(history, manager_ref)
        if manager_ref and manager is None:
            manager_task = InternalTask(
                method_name="UpsertEmployee",
                flow_kind=FlowKind.EMPLOYEE_UPSERT,
                operation="create",
                target_resource="employee",
                objective=internal_task.objective,
                search=_drop_empty(
                    {
                        "email": (manager_ref or {}).get("email"),
                        "firstName": (manager_ref or {}).get("firstName"),
                        "lastName": (manager_ref or {}).get("lastName"),
                        "count": 10,
                    }
                ),
                payload=_drop_empty(
                    {
                        "firstName": (manager_ref or {}).get("firstName"),
                        "lastName": (manager_ref or {}).get("lastName"),
                        "email": (manager_ref or {}).get("email"),
                    }
                ),
                notes=internal_task.notes,
            )
            manager_decision = self._next_employee_upsert(internal_task=manager_task, history=history)
            if manager_decision is not None:
                if manager_decision.kind == "finish" and _finish_reason_indicates_failure(manager_decision.reason):
                    return manager_decision
                if manager_decision.kind != "finish":
                    return manager_decision
            manager = _resolved_employee_by_ref(history, manager_ref)
            if manager is None:
                return None

        desired = dict(payload)
        if customer is not None and customer.get("id") not in {None, ""}:
            desired["customer"] = {"id": customer["id"]}
        if department is not None and department.get("id") not in {None, ""}:
            desired["department"] = {"id": department["id"]}
        if manager is not None and manager.get("id") not in {None, ""}:
            desired["projectManager"] = {"id": manager["id"]}

        if not desired:
            return None

        project = _resolved_project_from_internal(history, internal_task)
        if project is None:
            if internal_task.search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/project",
                predicate=lambda request: _request_contains_params(request, internal_task.search),
            ):
                return _action(
                    reason="Resolve the project before mutating it or creating a duplicate.",
                    method="GET",
                    path="/project",
                    params=internal_task.search,
                )

            if internal_task.operation == "update":
                return None

            return _action(
                reason="Create the project using the canonical OpenAPI fields and resolved linked entities.",
                method="POST",
                path="/project",
                json=desired,
            )

        if _entity_matches(project, desired):
            return PlannerDecision(kind="finish", reason="The project already satisfies the requested state.")

        project_id = project.get("id")
        if project_id in {None, ""}:
            return None

        update_payload = _build_update_payload(
            project,
            desired,
            allowed_fields=(
                "name",
                "number",
                "description",
                "reference",
                "startDate",
                "endDate",
                "invoiceReceiverEmail",
                "overdueNoticeEmail",
                "isFixedPrice",
                "fixedprice",
                "isPriceCeiling",
                "priceCeilingAmount",
                "customer",
                "department",
                "projectManager",
            ),
        )
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"/project/{project_id}",
            predicate=lambda request: _request_json_contains(request, update_payload),
        ):
            return None

        return _action(
            reason="Update the resolved project with the requested canonical fields.",
            method="PUT",
            path=f"/project/{project_id}",
            json=update_payload,
        )

    def _next_sales_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        create_invoice = bool(internal_task.payload.get("createInvoice"))
        register_payment = bool(internal_task.payload.get("registerPayment"))

        if create_invoice and (
            _has_success(history, method="PUT", path_suffix="/:invoice")
            or _has_success_exact(history, method="POST", path="/invoice")
        ):
            return PlannerDecision(kind="finish", reason="The sales workflow already completed its invoice step.")
        if not create_invoice and _has_success_exact(history, method="POST", path="/order"):
            return PlannerDecision(kind="finish", reason="The order has already been created.")

        customer = _resolved_customer_by_ref(history, internal_task.search or internal_task.payload.get("customer"))
        customer_payload = dict(internal_task.payload.get("customer") or {})
        if customer is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the customer before creating the sales order.",
                    method="GET",
                    path="/customer",
                    params=search_params,
                )
            if not customer_payload:
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/customer",
                predicate=lambda request: _request_json_contains(request, customer_payload),
            ):
                return None
            return _action(
                reason="Create the customer because the workflow did not find an exact match in the fresh account.",
                method="POST",
                path="/customer",
                json=customer_payload,
            )

        order_lines = list(internal_task.payload.get("orderLines") or [])
        if not order_lines:
            return None

        vat_lookup_params = _vat_type_lookup_params(
            order_lines,
            vat_date=internal_task.payload.get("orderDate") or internal_task.payload.get("deliveryDate"),
        )
        if vat_lookup_params is not None and not _all_order_line_vat_types_resolved(history, order_lines):
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/vatType",
                predicate=lambda request: _request_contains_params(request, vat_lookup_params),
            ):
                return _action(
                    reason="Resolve outgoing VAT types before creating order lines with explicit VAT rates.",
                    method="GET",
                    path="/ledger/vatType",
                    params=vat_lookup_params,
                )
            return None

        for line in order_lines:
            product_ref = {
                "productNumber": line.get("productNumber"),
                "name": line.get("description"),
            }
            if _is_blank(product_ref["productNumber"]) and _is_blank(product_ref["name"]):
                continue
            if _is_blank(product_ref["productNumber"]):
                continue
            product = _resolved_product_by_ref(
                history,
                product_ref,
            )
            if product is not None:
                continue

            search_params = _drop_empty({"productNumber": line.get("productNumber"), "count": 10})
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/product",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason=f"Resolve product {line.get('productNumber')} before creating the order.",
                    method="GET",
                    path="/product",
                    params=search_params,
                )

            product_payload = _product_payload_from_order_line(line)
            if not product_payload:
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/product",
                predicate=lambda request: _request_json_contains(request, product_payload),
            ):
                return None
            return _action(
                reason=f"Create product {line.get('productNumber')} because it does not exist in the fresh account.",
                method="POST",
                path="/product",
                json=product_payload,
            )

        order = _resolved_order_from_history(history)
        if order is None:
            order_payload = _build_order_payload_from_internal(internal_task, customer=customer, history=history)
            if order_payload is None:
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/order",
                predicate=lambda request: _request_json_contains(request, order_payload),
            ):
                return None
            return _action(
                reason="Create the order with the resolved customer and products.",
                method="POST",
                path="/order",
                json=order_payload,
            )

        if not create_invoice:
            return PlannerDecision(kind="finish", reason="The order workflow is complete.")

        order_id = order.get("id")
        if order_id in {None, ""}:
            return None

        invoice_date = internal_task.payload.get("invoiceDate") or task_analysis.payload_fields.get("invoiceDate")
        invoice_due_date = (
            internal_task.payload.get("invoiceDueDate")
            or internal_task.payload.get("paymentDate")
            or invoice_date
        )
        params: dict[str, Any] = {
            "invoiceDate": invoice_date,
        }

        if register_payment:
            payment_type_id = best_effort_payment_type_id(task_analysis, history)
            if payment_type_id in {None, ""}:
                payment_type_params: dict[str, Any] = {"count": 10, "fields": "id,description"}
                description = (
                    internal_task.payload.get("paymentTypeDescription")
                    or best_effort_payment_type_description(task_analysis)
                )
                if description:
                    payment_type_params["description"] = description
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/invoice/paymentType",
                    predicate=lambda request: _request_contains_params(request, payment_type_params),
                ):
                    return _action(
                        reason="Resolve an outgoing invoice payment type before invoicing the order as fully paid.",
                        method="GET",
                        path="/invoice/paymentType",
                        params=payment_type_params,
                    )
                payment_type_id = _fallback_first_payment_type_id(history)
                if payment_type_id in {None, ""}:
                    return None

            total_amount = _sales_total_amount(internal_task, history=history)
            if total_amount in {None, ""}:
                return None
            params["paymentTypeId"] = payment_type_id
            params["paidAmount"] = total_amount

        invoice_action_path = f"/order/{order_id}/:invoice"
        invoice_action_params = _drop_empty(params)
        if _has_api_error_exact_where(
            history,
            method="PUT",
            path=invoice_action_path,
            predicate=lambda request: _request_contains_params(request, invoice_action_params),
        ):
            invoice_payload = _build_invoice_payload_from_order(
                order_id=order_id,
                customer_id=customer.get("id"),
                invoice_date=invoice_date,
                invoice_due_date=invoice_due_date,
            )
            invoice_query = _drop_empty(
                {
                    "paymentTypeId": invoice_action_params.get("paymentTypeId"),
                    "paidAmount": invoice_action_params.get("paidAmount"),
                }
            )
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/invoice",
                predicate=lambda request: _request_contains_params(request, invoice_query)
                and _request_json_contains(request, invoice_payload),
            ):
                return None
            return _action(
                reason="Fallback to direct invoice creation from the resolved order after the order invoice action returned a validation error.",
                method="POST",
                path="/invoice",
                params=invoice_query,
                json=invoice_payload,
            )

        return _action(
            reason="Convert the resolved order into an invoice using the canonical Tripletex action endpoint.",
            method="PUT",
            path=invoice_action_path,
            params=invoice_action_params,
        )

    def _next_supplier_invoice_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if _has_success_exact(history, method="POST", path="/incomingInvoice"):
            return PlannerDecision(kind="finish", reason="The supplier invoice workflow is complete.")

        supplier_ref = internal_task.search or internal_task.payload.get("supplier")
        supplier_payload = dict(internal_task.payload.get("supplier") or {})
        supplier = _resolved_supplier_by_ref(history, supplier_ref)
        if supplier is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/supplier",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the supplier before registering the supplier invoice.",
                    method="GET",
                    path="/supplier",
                    params=search_params,
                )
            if supplier_payload and not _has_attempt_exact_where(
                history,
                method="POST",
                path="/supplier",
                predicate=lambda request: _request_json_contains(request, supplier_payload),
            ):
                return _action(
                    reason="Create the supplier because the invoice refers to a vendor that does not exist in the fresh account.",
                    method="POST",
                    path="/supplier",
                    json=supplier_payload,
                )
            return None

        account_number = internal_task.payload.get("accountNumber")
        if account_number in {None, ""}:
            default_account = _resolved_default_supplier_invoice_account(history)
            if default_account is None:
                default_account_search = {
                    "isApplicableForSupplierInvoice": True,
                    "count": 100,
                    "fields": "id,number,name,isApplicableForSupplierInvoice,vatLocked",
                }
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/ledger/account",
                    predicate=lambda request: _request_contains_params(request, default_account_search),
                ):
                    return _action(
                        reason="Resolve a default supplier-invoice ledger account because the prompt did not specify one.",
                        method="GET",
                        path="/ledger/account",
                        params=default_account_search,
                    )
                return None
            account_number = default_account.get("number")

        account = _resolved_ledger_account_from_history(history, account_number=account_number)
        if account is None:
            account_search = {
                "number": account_number,
                "isApplicableForSupplierInvoice": True,
                "count": 10,
                "fields": "id,number,name,isApplicableForSupplierInvoice,vatLocked",
            }
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/account",
                predicate=lambda request: _request_contains_params(request, account_search),
            ):
                return _action(
                    reason="Resolve the supplier-invoice ledger account before posting the incoming invoice.",
                    method="GET",
                    path="/ledger/account",
                    params=account_search,
                )

            fallback_account_search = {
                "number": account_number,
                "count": 10,
                "fields": "id,number,name,isApplicableForSupplierInvoice,vatLocked",
            }
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/account",
                predicate=lambda request: _request_contains_params(request, fallback_account_search),
            ):
                return _action(
                    reason="Retry ledger-account resolution without the supplier-invoice applicability filter to handle account-specific sandbox variance.",
                    method="GET",
                    path="/ledger/account",
                    params=fallback_account_search,
                )
            return None

        vat_type_ref = internal_task.payload.get("vatType")
        vat_type = None
        account_default_vat_type_id = account.get("vatTypeId") if isinstance(account, dict) else None
        if isinstance(vat_type_ref, dict):
            vat_type = _resolved_vat_type_by_ref(history, vat_type_ref)
            requested_percentage = vat_type_ref.get("percentage")
            logger.info(
                "supplier_invoice.vat_resolution requested_percentage=%s account_vat_type_id=%s resolved_vat_type_id=%s",
                requested_percentage,
                account_default_vat_type_id,
                vat_type.get("id") if isinstance(vat_type, dict) else None,
            )
            if vat_type is None and account_default_vat_type_id in {None, ""}:
                vat_type_search = {
                    "typeOfVat": "INCOMING_INVOICE",
                    "vatDate": internal_task.payload.get("invoiceDate"),
                    "count": 100,
                    "fields": "id,name,displayName,number,percentage",
                }
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/ledger/vatType",
                    predicate=lambda request: _request_contains_params(request, vat_type_search),
                ):
                    return _action(
                        reason="Resolve incoming VAT types before registering the supplier invoice line with explicit VAT.",
                        method="GET",
                        path="/ledger/vatType",
                        params=vat_type_search,
                    )
                fallback_vat_type_search = {
                    "typeOfVat": "INCOMING",
                    "vatDate": internal_task.payload.get("invoiceDate"),
                    "count": 100,
                    "fields": "id,name,displayName,number,percentage",
                }
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/ledger/vatType",
                    predicate=lambda request: _request_contains_params(request, fallback_vat_type_search),
                ):
                    return _action(
                        reason="Retry incoming VAT resolution with the generic incoming VAT bucket after the invoice-specific bucket did not yield a usable result.",
                        method="GET",
                        path="/ledger/vatType",
                        params=fallback_vat_type_search,
                    )
                return None
            if vat_type is None and account_default_vat_type_id not in {None, ""}:
                logger.info(
                    "supplier_invoice.vat_resolution using_account_default_vat_type_id=%s",
                    account_default_vat_type_id,
                )

        invoice_payload = _build_incoming_invoice_payload_from_internal(
            internal_task,
            supplier=supplier,
            account=account,
            vat_type=vat_type,
            voucher_type_id=_resolved_supplier_invoice_voucher_type_id(
                history,
                voucher_type_name=internal_task.payload.get("voucherTypeName"),
            ),
        )
        if invoice_payload is None:
            return None

        if _has_api_error_exact_where(
            history,
            method="POST",
            path="/incomingInvoice",
            predicate=lambda request: _request_json_contains(request, invoice_payload),
        ):
            latest_error = _latest_api_error_exact_where(
                history,
                method="POST",
                path="/incomingInvoice",
                predicate=lambda request: _request_json_contains(request, invoice_payload),
            )
            if latest_error is not None and latest_error.get("status_code") in {401, 403}:
                return PlannerDecision(
                    kind="finish",
                    reason=(
                        "Unable to register the supplier invoice through the canonical incoming-invoice workflow. "
                        f"Latest Tripletex error: {_tripletex_error_summary(latest_error)}"
                    ),
                )
            voucher_type_search = {"count": 50, "fields": "id,name"}
            voucher_type_name = internal_task.payload.get("voucherTypeName")
            if voucher_type_name not in {None, ""}:
                voucher_type_search["name"] = voucher_type_name
            if invoice_payload.get("invoiceHeader", {}).get("voucherTypeId") in {None, ""} and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/voucherType",
                predicate=lambda request: _request_contains_params(request, voucher_type_search),
            ):
                return _action(
                    reason="Resolve the voucher type before retrying supplier invoice registration after a validation error.",
                    method="GET",
                    path="/ledger/voucherType",
                    params=voucher_type_search,
                )
            if latest_error is None:
                return None
            return PlannerDecision(
                kind="finish",
                reason=(
                    "Unable to register the supplier invoice through the canonical incoming-invoice workflow. "
                    f"Latest Tripletex error: {_tripletex_error_summary(latest_error)}"
                ),
            )

        if _has_attempt_exact_where(
            history,
            method="POST",
            path="/incomingInvoice",
            predicate=lambda request: _request_json_contains(request, invoice_payload),
        ):
            return None

        return _action(
            reason="Register the supplier invoice through the canonical incoming-invoice endpoint.",
            method="POST",
            path="/incomingInvoice",
            json=invoice_payload,
        )

    def _next_invoice_credit_note_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if _has_success(history, method="PUT", path_suffix="/:createCreditNote"):
            return PlannerDecision(kind="finish", reason="The credit note workflow is complete.")

        customer = _resolved_customer_by_ref(history, internal_task.search or internal_task.payload.get("customer"))
        if customer is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the customer before locating the invoice that must be credited.",
                    method="GET",
                    path="/customer",
                    params=search_params,
                )
            return None

        invoice = _resolved_credit_note_target_invoice(history, internal_task=internal_task)
        if invoice is None:
            search_params = _credit_note_invoice_search_params(
                task_analysis,
                customer_id=customer.get("id"),
                invoice_number=internal_task.payload.get("invoiceNumber"),
            )
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Locate the outgoing invoice before creating the requested credit note.",
                    method="GET",
                    path="/invoice",
                    params=search_params,
                )
            return None

        invoice_id = invoice.get("id")
        if invoice_id in {None, ""}:
            return None

        credit_note_params = _drop_empty(
            {
                "date": internal_task.payload.get("creditNoteDate") or default_action_date(task_analysis, "date"),
                "comment": internal_task.payload.get("comment"),
            }
        )
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"/invoice/{invoice_id}/:createCreditNote",
            predicate=lambda request: _request_contains_params(request, credit_note_params),
        ):
            return None

        return _action(
            reason="Create a full credit note from the resolved invoice using the canonical invoice action endpoint.",
            method="PUT",
            path=f"/invoice/{invoice_id}/:createCreditNote",
            params=credit_note_params,
        )

    def _next_project_time_invoice_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        payload = dict(internal_task.payload)
        customer_ref = dict(payload.get("customerRef") or {})
        employee_ref = dict(payload.get("employeeRef") or {})
        project_ref = dict(payload.get("projectRef") or {})
        activity_ref = dict(payload.get("activityRef") or {})
        entry_date = payload.get("date")
        hours = payload.get("hours")
        hourly_rate = payload.get("hourlyRate")

        if entry_date in {None, ""} or hours in {None, ""} or hourly_rate in {None, ""}:
            return None

        customer = _resolved_customer_by_ref(history, customer_ref)
        if customer is None:
            customer_search = _drop_empty(
                {
                    "organizationNumber": customer_ref.get("organizationNumber"),
                    "customerName": customer_ref.get("customerName") or customer_ref.get("name"),
                    "count": 10,
                    "fields": "id,name,organizationNumber",
                }
            )
            if customer_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request: _request_contains_params(request, customer_search),
            ):
                return _action(
                    reason="Resolve the customer before logging project hours and invoicing them.",
                    method="GET",
                    path="/customer",
                    params=customer_search,
                )

            customer_payload = _drop_empty(
                {
                    "name": customer_ref.get("customerName") or customer_ref.get("name"),
                    "organizationNumber": customer_ref.get("organizationNumber"),
                }
            )
            if not customer_payload:
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/customer",
                predicate=lambda request: _request_json_contains(request, customer_payload),
            ):
                return None
            return _action(
                reason="Create the customer because the project-billing workflow needs a billable receiver.",
                method="POST",
                path="/customer",
                json=customer_payload,
            )

        customer_id = customer.get("id")
        if customer_id in {None, ""}:
            return None

        employee = _resolved_employee_by_ref(history, employee_ref)
        if employee is None:
            employee_search = _drop_empty(
                {
                    "email": employee_ref.get("email"),
                    "firstName": employee_ref.get("firstName"),
                    "lastName": employee_ref.get("lastName"),
                    "count": 10,
                    "fields": "id,version,firstName,lastName,email",
                }
            )
            if employee_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, employee_search),
            ):
                return _action(
                    reason="Resolve the employee before registering timesheet hours.",
                    method="GET",
                    path="/employee",
                    params=employee_search,
                )

            employee_payload = _drop_empty(
                {
                    "firstName": employee_ref.get("firstName"),
                    "lastName": employee_ref.get("lastName"),
                    "email": employee_ref.get("email"),
                }
            )
            if not employee_payload.get("firstName") or not employee_payload.get("lastName"):
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/employee",
                predicate=lambda request: _request_json_contains(request, employee_payload),
            ):
                return None
            return _action(
                reason="Create the employee because the requested time registration refers to a missing employee.",
                method="POST",
                path="/employee",
                json=employee_payload,
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return None

        project = _resolved_project_by_ref(history, project_ref)
        if project is None:
            project_search = _drop_empty(
                {
                    "name": project_ref.get("name"),
                    "number": project_ref.get("number"),
                    "customerId": customer_id,
                    "isClosed": False,
                    "count": 10,
                    "fields": "id,name,number,isClosed,customer",
                }
            )
            if project_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/project",
                predicate=lambda request: _request_contains_params(request, project_search),
            ):
                return _action(
                    reason="Resolve the project before registering hours and invoicing them.",
                    method="GET",
                    path="/project",
                    params=project_search,
                )

            project_payload = _drop_empty(
                {
                    "name": project_ref.get("name"),
                    "number": project_ref.get("number"),
                    "customer": {"id": customer_id},
                }
            )
            if not project_payload.get("name") and not project_payload.get("number"):
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/project",
                predicate=lambda request: _request_json_contains(request, project_payload),
            ):
                return None
            return _action(
                reason="Create the project so the requested hours can be registered and billed.",
                method="POST",
                path="/project",
                json=project_payload,
            )

        project_id = project.get("id")
        if project_id in {None, ""}:
            return None

        activity = _resolved_activity_by_ref(history, activity_ref)
        activity_name = activity_ref.get("name")
        if activity is None:
            timesheet_activity_search = _drop_empty(
                {
                    "projectId": project_id,
                    "employeeId": employee_id,
                    "date": entry_date,
                    "query": activity_name,
                    "count": 25,
                    "fields": "id,name,number,isChargeable,isProjectActivity",
                }
            )
            if timesheet_activity_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/activity/>forTimeSheet",
                predicate=lambda request: _request_contains_params(request, timesheet_activity_search),
            ):
                return _action(
                    reason="Resolve an applicable activity for the employee, project, and date before registering time.",
                    method="GET",
                    path="/activity/>forTimeSheet",
                    params=timesheet_activity_search,
                )

            generic_activity_search = _drop_empty(
                {
                    "name": activity_name,
                    "number": activity_ref.get("number"),
                    "isChargeable": True,
                    "count": 10,
                    "fields": "id,name,number,isChargeable,isProjectActivity",
                }
            )
            if generic_activity_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/activity",
                predicate=lambda request: _request_contains_params(request, generic_activity_search),
            ):
                return _action(
                    reason="Search the generic activity catalog before creating a new activity.",
                    method="GET",
                    path="/activity",
                    params=generic_activity_search,
                )

            activity_payload = _drop_empty(
                {
                    "name": activity_name,
                    "number": activity_ref.get("number"),
                    "isProjectActivity": True,
                    "isChargeable": True,
                }
            )
            if not activity_payload.get("name"):
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/activity",
                predicate=lambda request: _request_json_contains(request, activity_payload),
            ):
                return None
            return _action(
                reason="Create the missing project activity so the requested hours can be logged consistently.",
                method="POST",
                path="/activity",
                json=activity_payload,
            )

        activity_id = activity.get("id")
        if activity_id in {None, ""}:
            return None

        timesheet_search = {
            "employeeId": employee_id,
            "projectId": project_id,
            "activityId": activity_id,
            "dateFrom": entry_date,
            "dateTo": entry_date,
            "count": 10,
            "fields": "id,version,date,hours,projectChargeableHours,comment,chargeable",
        }
        timesheet_entry = _resolved_timesheet_entry_from_history(
            history,
            employee_id=employee_id,
            project_id=project_id,
            activity_id=activity_id,
            entry_date=entry_date,
        )
        if timesheet_entry is None:
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/timesheet/entry",
                predicate=lambda request: _request_contains_params(request, timesheet_search),
            ):
                return _action(
                    reason="Search for an existing timesheet entry before creating a duplicate.",
                    method="GET",
                    path="/timesheet/entry",
                    params=timesheet_search,
                )

            create_entry_payload = _build_timesheet_entry_payload(
                employee_id=employee_id,
                project_id=project_id,
                activity_id=activity_id,
                entry_date=entry_date,
                hours=hours,
                hourly_rate=hourly_rate,
                comment=payload.get("comment"),
            )
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/timesheet/entry",
                predicate=lambda request: _request_json_contains(request, create_entry_payload),
            ):
                return None
            return _action(
                reason="Register the requested timesheet hours on the resolved employee, project, and activity.",
                method="POST",
                path="/timesheet/entry",
                json=create_entry_payload,
            )

        if not _timesheet_entry_matches(
            timesheet_entry,
            entry_date=entry_date,
            hours=hours,
            hourly_rate=hourly_rate,
            comment=payload.get("comment"),
        ):
            entry_id = timesheet_entry.get("id")
            entry_version = timesheet_entry.get("version")
            if entry_id in {None, ""} or entry_version in {None, ""}:
                return None
            update_entry_payload = _build_timesheet_entry_payload(
                employee_id=employee_id,
                project_id=project_id,
                activity_id=activity_id,
                entry_date=entry_date,
                hours=hours,
                hourly_rate=hourly_rate,
                comment=payload.get("comment"),
                entry_id=entry_id,
                entry_version=entry_version,
            )
            if _has_attempt_exact_where(
                history,
                method="PUT",
                path=f"/timesheet/entry/{entry_id}",
                predicate=lambda request: _request_json_contains(request, update_entry_payload),
            ):
                return None
            return _action(
                reason="Update the existing timesheet entry to the requested hours and hourly rate.",
                method="PUT",
                path=f"/timesheet/entry/{entry_id}",
                json=update_entry_payload,
            )

        if _has_success(history, method="PUT", path_suffix="/:invoice") or _has_success_exact(
            history,
            method="POST",
            path="/invoice",
        ):
            return PlannerDecision(kind="finish", reason="The timesheet and invoice workflow already completed.")

        order = _resolved_order_from_history(history)
        if order is None:
            order_payload = _build_project_time_invoice_order_payload(
                customer_id=customer_id,
                project_id=project_id,
                order_date=payload.get("orderDate") or entry_date,
                hours=hours,
                hourly_rate=hourly_rate,
                activity_name=activity.get("name") or activity_name,
                project_name=project.get("name") or project_ref.get("name"),
            )
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/order",
                predicate=lambda request: _request_json_contains(request, order_payload),
            ):
                return None
            return _action(
                reason="Create an order line from the registered project hours so it can be invoiced immediately.",
                method="POST",
                path="/order",
                json=order_payload,
            )

        order_id = order.get("id")
        if order_id in {None, ""}:
            return None

        invoice_date = payload.get("invoiceDate") or entry_date
        invoice_due_date = payload.get("invoiceDueDate") or invoice_date
        invoice_action_path = f"/order/{order_id}/:invoice"
        invoice_action_params = {"invoiceDate": invoice_date}
        if _has_api_error_exact_where(
            history,
            method="PUT",
            path=invoice_action_path,
            predicate=lambda request: _request_contains_params(request, invoice_action_params),
        ):
            invoice_payload = _build_invoice_payload_from_order(
                order_id=order_id,
                customer_id=customer_id,
                invoice_date=invoice_date,
                invoice_due_date=invoice_due_date,
            )
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/invoice",
                predicate=lambda request: _request_json_contains(request, invoice_payload),
            ):
                return None
            return _action(
                reason="Fallback to direct invoice creation from the order after the order invoice action returned a validation error.",
                method="POST",
                path="/invoice",
                json=invoice_payload,
            )

        return _action(
            reason="Invoice the generated order for the logged project hours.",
            method="PUT",
            path=invoice_action_path,
            params=invoice_action_params,
        )

    def _next_project_lifecycle_workflow(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        payload = dict(internal_task.payload)
        project_payload = dict(payload.get("project") or {})
        customer_ref = dict(payload.get("customerRef") or project_payload.get("customerRef") or {})
        default_activity_ref = dict(payload.get("defaultActivity") or {})
        timesheet_entries = [entry for entry in (payload.get("timesheetEntries") or []) if isinstance(entry, dict)]
        supplier_invoice = dict(payload.get("supplierInvoice") or {})
        invoice_payload = dict(payload.get("invoice") or {})

        project_task = InternalTask(
            method_name="UpsertProject",
            flow_kind=FlowKind.PROJECT_UPSERT,
            operation="update",
            target_resource="project",
            objective=internal_task.objective,
            search=_drop_empty(
                {
                    "name": project_payload.get("name"),
                    "number": project_payload.get("number"),
                    "count": 10,
                }
            ),
            payload=project_payload,
            notes=internal_task.notes,
        )
        project_decision = self._next_project_upsert(internal_task=project_task, history=history)
        if project_decision is not None:
            if project_decision.kind == "finish" and _finish_reason_indicates_failure(project_decision.reason):
                return project_decision
            if project_decision.kind != "finish":
                return project_decision

        project = _resolved_project_by_ref(
            history,
            {
                "name": project_payload.get("name"),
                "number": project_payload.get("number"),
            },
        )
        if project is None:
            return None

        project_id = project.get("id")
        if project_id in {None, ""}:
            return None

        activity_ref = dict(default_activity_ref or {"name": "Project work", "isChargeable": True, "isProjectActivity": True})
        activity = _resolved_activity_by_ref(history, activity_ref)
        if activity is None:
            activity_search = _drop_empty(
                {
                    "name": activity_ref.get("name"),
                    "number": activity_ref.get("number"),
                    "isChargeable": True,
                    "count": 10,
                    "fields": "id,name,number,isChargeable,isProjectActivity",
                }
            )
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/activity",
                predicate=lambda request: _request_contains_params(request, activity_search),
            ):
                return _action(
                    reason="Resolve the project activity before registering project lifecycle hours.",
                    method="GET",
                    path="/activity",
                    params=activity_search,
                )

            activity_payload = _drop_empty(
                {
                    "name": activity_ref.get("name") or "Project work",
                    "number": activity_ref.get("number"),
                    "isProjectActivity": activity_ref.get("isProjectActivity", True),
                    "isChargeable": activity_ref.get("isChargeable", True),
                }
            )
            if not _has_attempt_exact_where(
                history,
                method="POST",
                path="/activity",
                predicate=lambda request: _request_json_contains(request, activity_payload),
            ):
                return _action(
                    reason="Create a default chargeable project activity for the lifecycle workflow.",
                    method="POST",
                    path="/activity",
                    json=activity_payload,
                )
            return None

        activity_id = activity.get("id")
        if activity_id in {None, ""}:
            return None

        for entry in timesheet_entries:
            employee_ref = dict(entry.get("employeeRef") or {})
            employee_task = InternalTask(
                method_name="UpsertEmployee",
                flow_kind=FlowKind.EMPLOYEE_UPSERT,
                operation="update",
                target_resource="employee",
                objective=internal_task.objective,
                search=_drop_empty(
                    {
                        "email": employee_ref.get("email"),
                        "firstName": employee_ref.get("firstName"),
                        "lastName": employee_ref.get("lastName"),
                        "count": 10,
                    }
                ),
                payload=_drop_empty(
                    {
                        "firstName": employee_ref.get("firstName"),
                        "lastName": employee_ref.get("lastName"),
                        "email": employee_ref.get("email"),
                    }
                ),
                notes=internal_task.notes,
            )
            employee_decision = self._next_employee_upsert(internal_task=employee_task, history=history)
            if employee_decision is not None:
                if employee_decision.kind == "finish" and _finish_reason_indicates_failure(employee_decision.reason):
                    return employee_decision
                if employee_decision.kind != "finish":
                    return employee_decision

            employee = _resolved_employee_by_ref(history, employee_ref)
            if employee is None:
                return None

            employee_id = employee.get("id")
            if employee_id in {None, ""}:
                return None

            entry_date = entry.get("date") or default_action_date(task_analysis, "date")
            hours = entry.get("hours")
            if hours in {None, ""}:
                continue
            comment = entry.get("comment")
            timesheet_search = {
                "employeeId": employee_id,
                "projectId": project_id,
                "activityId": activity_id,
                "dateFrom": entry_date,
                "dateTo": entry_date,
                "count": 10,
                "fields": "id,version,date,hours,projectChargeableHours,comment,chargeable",
            }
            timesheet_entry = _resolved_timesheet_entry_from_history(
                history,
                employee_id=employee_id,
                project_id=project_id,
                activity_id=activity_id,
                entry_date=entry_date,
            )
            if timesheet_entry is None:
                if not _has_attempt_exact_where(
                    history,
                    method="GET",
                    path="/timesheet/entry",
                    predicate=lambda request: _request_contains_params(request, timesheet_search),
                ):
                    return _action(
                        reason="Resolve any existing project timesheet entry before creating a duplicate entry.",
                        method="GET",
                        path="/timesheet/entry",
                        params=timesheet_search,
                    )

                create_entry_payload = _build_timesheet_entry_payload(
                    employee_id=employee_id,
                    project_id=project_id,
                    activity_id=activity_id,
                    entry_date=entry_date,
                    hours=hours,
                    hourly_rate=entry.get("hourlyRate") or 0,
                    comment=comment,
                )
                if _has_attempt_exact_where(
                    history,
                    method="POST",
                    path="/timesheet/entry",
                    predicate=lambda request: _request_json_contains(request, create_entry_payload),
                ):
                    return None
                return _action(
                    reason="Register the project lifecycle timesheet entry for the resolved employee.",
                    method="POST",
                    path="/timesheet/entry",
                    json=create_entry_payload,
                )

            if not _timesheet_entry_matches(
                timesheet_entry,
                entry_date=entry_date,
                hours=hours,
                hourly_rate=entry.get("hourlyRate") or 0,
                comment=comment,
            ):
                entry_id = timesheet_entry.get("id")
                entry_version = timesheet_entry.get("version")
                if entry_id in {None, ""} or entry_version in {None, ""}:
                    return None
                update_entry_payload = _build_timesheet_entry_payload(
                    employee_id=employee_id,
                    project_id=project_id,
                    activity_id=activity_id,
                    entry_date=entry_date,
                    hours=hours,
                    hourly_rate=entry.get("hourlyRate") or 0,
                    comment=comment,
                    entry_id=entry_id,
                    entry_version=entry_version,
                )
                if _has_attempt_exact_where(
                    history,
                    method="PUT",
                    path=f"/timesheet/entry/{entry_id}",
                    predicate=lambda request: _request_json_contains(request, update_entry_payload),
                ):
                    return None
                return _action(
                    reason="Update the project lifecycle timesheet entry to the requested hours.",
                    method="PUT",
                    path=f"/timesheet/entry/{entry_id}",
                    json=update_entry_payload,
                )

        if supplier_invoice:
            supplier_task = InternalTask(
                method_name="RegisterSupplierInvoice",
                flow_kind=FlowKind.SUPPLIER_INVOICE_WORKFLOW,
                operation="create",
                target_resource="supplierinvoice",
                objective=internal_task.objective,
                search=_drop_empty(
                    {
                        "organizationNumber": supplier_invoice.get("supplierOrganizationNumber"),
                        "email": supplier_invoice.get("supplierEmail"),
                        "count": 10,
                        "fields": "id,name,organizationNumber,email,invoiceEmail",
                    }
                ),
                payload=_drop_empty(
                    {
                        "supplier": {
                            "name": supplier_invoice.get("supplierName"),
                            "organizationNumber": supplier_invoice.get("supplierOrganizationNumber"),
                            "email": supplier_invoice.get("supplierEmail"),
                        },
                        "invoiceNumber": supplier_invoice.get("invoiceNumber"),
                        "description": supplier_invoice.get("description"),
                        "accountNumber": supplier_invoice.get("accountNumber"),
                        "amountIncludingVat": supplier_invoice.get("amountIncludingVat"),
                        "vatType": {
                            "direction": "INCOMING",
                            "percentage": supplier_invoice.get("vatRate"),
                        },
                        "invoiceDate": supplier_invoice.get("invoiceDate") or invoice_payload.get("invoiceDate"),
                        "dueDate": supplier_invoice.get("dueDate") or invoice_payload.get("invoiceDate"),
                        "voucherTypeName": supplier_invoice.get("voucherTypeName"),
                    }
                ),
                notes=internal_task.notes,
            )
            supplier_decision = self._next_supplier_invoice_workflow(
                internal_task=supplier_task,
                task_analysis=task_analysis,
                history=history,
            )
            if supplier_decision is not None:
                if supplier_decision.kind == "finish" and _finish_reason_indicates_failure(supplier_decision.reason):
                    return supplier_decision
                if supplier_decision.kind != "finish":
                    return supplier_decision

        sales_order_lines = _project_lifecycle_order_lines(
            project_name=project.get("name") or project_payload.get("name"),
            timesheet_entries=timesheet_entries,
            budget_amount=invoice_payload.get("budgetAmount"),
        )
        if not sales_order_lines:
            return None

        sales_task = InternalTask(
            method_name="RunSalesWorkflow",
            flow_kind=FlowKind.SALES_WORKFLOW,
            operation="invoice",
            target_resource="invoice",
            objective=internal_task.objective,
            search=_drop_empty(
                {
                    "organizationNumber": customer_ref.get("organizationNumber"),
                    "customerName": customer_ref.get("customerName"),
                    "count": 10,
                }
            ),
            payload=_drop_empty(
                {
                    "customer": {
                        "name": customer_ref.get("customerName"),
                        "organizationNumber": customer_ref.get("organizationNumber"),
                    },
                    "project": {"id": project_id},
                    "orderLines": sales_order_lines,
                    "orderDate": invoice_payload.get("invoiceDate") or default_action_date(task_analysis, "date"),
                    "deliveryDate": invoice_payload.get("invoiceDate") or default_action_date(task_analysis, "date"),
                    "invoiceDate": invoice_payload.get("invoiceDate") or default_action_date(task_analysis, "date"),
                    "invoiceDueDate": invoice_payload.get("invoiceDueDate") or invoice_payload.get("invoiceDate"),
                    "createInvoice": True,
                }
            ),
            notes=internal_task.notes,
        )
        sales_decision = self._next_sales_workflow(
            internal_task=sales_task,
            task_analysis=task_analysis,
            history=history,
        )
        if sales_decision is not None:
            if sales_decision.kind == "finish":
                return PlannerDecision(kind="finish", reason="The project lifecycle workflow is complete.")
            return sales_decision

        return None

    def _next_invoice_payment(
        self,
        *,
        internal_task: InternalTask,
        task_analysis: TaskAnalysis,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        if _has_success(history, method="PUT", path_suffix="/:payment"):
            return PlannerDecision(kind="finish", reason="Invoice payment action already completed.")

        customer_ref = _invoice_payment_customer_ref(internal_task)
        customer = _resolved_customer_by_ref(history, customer_ref)
        customer_id = internal_task.search.get("customerId")
        if customer_id in {None, ""} and customer is None and customer_ref:
            customer_search = _invoice_payment_customer_search_params(internal_task)
            if customer_search and not _has_attempt_exact_where(
                history,
                method="GET",
                path="/customer",
                predicate=lambda request, expected=customer_search: _request_contains_params(request, expected),
            ):
                return _action(
                    reason="Resolve the customer before locating the outgoing invoice to register payment on.",
                    method="GET",
                    path="/customer",
                    params=customer_search,
                )
            if customer_search:
                customer = _resolved_customer_by_ref(history, customer_ref)
        if customer_id in {None, ""} and customer is not None:
            customer_id = customer.get("id")

        invoice = _resolved_invoice_payment_target_invoice(
            history,
            internal_task=internal_task,
            task_analysis=task_analysis,
            customer_id=customer_id,
        )
        if invoice is None:
            search_params = _invoice_payment_invoice_search_params(
                internal_task=internal_task,
                task_analysis=task_analysis,
                customer_id=customer_id,
            )
            if search_params is None:
                return None
            if _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice",
                predicate=lambda request, expected=search_params: _request_contains_params(request, expected),
            ):
                return None
            return _action(
                reason="Resolve the target invoice with a spec-valid invoice search before registering payment.",
                method="GET",
                path="/invoice",
                params=search_params,
            )

        invoice_id = invoice.get("id")
        if invoice_id in {None, ""}:
            return None

        payment_type_id = best_effort_payment_type_id(task_analysis, history)
        if payment_type_id in {None, ""}:
            params: dict[str, Any] = {"count": 10}
            description = internal_task.payload.get("paymentTypeDescription") or best_effort_payment_type_description(task_analysis)
            if description:
                params["description"] = description
            if _has_attempt_exact_where(
                history,
                method="GET",
                path="/invoice/paymentType",
                predicate=lambda request: _request_contains_params(request, params),
            ):
                payment_type_id = _fallback_first_payment_type_id(history)
                if payment_type_id in {None, ""}:
                    return None
            else:
                return _action(
                    reason="Resolve paymentTypeId through the dedicated invoice payment-type endpoint before registering payment.",
                    method="GET",
                    path="/invoice/paymentType",
                    params=params,
                )

        paid_amount = internal_task.payload.get("paidAmount") or best_effort_amount(task_analysis, history)
        if paid_amount in {None, ""}:
            return None

        return _action(
            reason="Register payment on the resolved invoice using the canonical Tripletex payment action.",
            method="PUT",
            path=f"/invoice/{invoice_id}/:payment",
            params={
                "paymentDate": internal_task.payload.get("paymentDate"),
                "paymentTypeId": payment_type_id,
                "paidAmount": paid_amount,
            },
        )

    def _next_employee_admin(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        template = internal_task.payload.get("template")
        if template is None:
            return None

        if _has_success(history, method="PUT", path_prefix="/employee/entitlement/"):
            return PlannerDecision(kind="finish", reason="Employee entitlement action already completed.")

        employee = _resolved_employee_from_internal(history, internal_task)
        if employee is None:
            if internal_task.operation != "update":
                payload = dict(internal_task.payload)
                if payload is None:
                    return None
                payload["userType"] = "EXTENDED"
                payload.pop("template", None)
                if _has_attempt_exact_where(
                    history,
                    method="POST",
                    path="/employee",
                    predicate=lambda request: _request_json_contains(request, payload),
                ):
                    return None
                return _action(
                    reason="Create the employee with EXTENDED access so entitlement templates can be applied safely.",
                    method="POST",
                    path="/employee",
                    json=payload,
                )

            search_params = internal_task.search
            if search_params is None:
                return None
            if _has_attempt_exact_where(
                history,
                method="GET",
                path="/employee",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return None
            return _action(
                reason="Resolve the employee before applying administrator entitlements.",
                method="GET",
                path="/employee",
                params=search_params,
            )

        employee_id = employee.get("id")
        if employee_id in {None, ""}:
            return None

        if employee.get("userType") != "EXTENDED":
            if employee.get("version") in {None, ""}:
                return _action(
                    reason="Fetch the employee record with version information before upgrading userType.",
                    method="GET",
                    path=f"/employee/{employee_id}",
                )

            updated_employee = _build_update_payload(
                employee,
                {"userType": "EXTENDED"},
                allowed_fields=(
                    "firstName",
                    "lastName",
                    "email",
                    "employeeNumber",
                    "phoneNumberMobile",
                    "phoneNumberWork",
                    "comments",
                    "userType",
                ),
            )
            return _action(
                reason="Upgrade the employee to EXTENDED access before applying administrator entitlements.",
                method="PUT",
                path=f"/employee/{employee_id}",
                json=updated_employee,
            )

        return _action(
            reason="Grant the entitlement template needed for the requested administrator-style role.",
            method="PUT",
            path="/employee/entitlement/:grantEntitlementsByTemplate",
            params={
                "employeeId": employee_id,
                "template": template,
            },
        )

    def _next_ledger_dimension_workflow(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
    ) -> PlannerDecision | None:
        dimension_name = internal_task.payload.get("dimensionName")
        if dimension_name in {None, ""}:
            return None

        dimension = _resolved_dimension_name_from_history(history, dimension_name=str(dimension_name))
        if dimension is None:
            if not _has_attempt_exact(history, method="GET", path="/ledger/accountingDimensionName"):
                return _action(
                    reason="List existing accounting dimensions before creating a new one.",
                    method="GET",
                    path="/ledger/accountingDimensionName",
                    params={"count": 20, "fields": "id,dimensionName,dimensionIndex,active"},
                )

            create_payload = {
                "dimensionName": dimension_name,
                "description": dimension_name,
                "active": True,
            }
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/ledger/accountingDimensionName",
                predicate=lambda request: _request_json_contains(request, create_payload),
            ):
                return None
            return _action(
                reason="Create the requested free accounting dimension using the canonical OpenAPI field names.",
                method="POST",
                path="/ledger/accountingDimensionName",
                json=create_payload,
            )

        dimension_index = dimension.get("dimensionIndex")
        if dimension_index in {None, ""}:
            return None

        values = list(internal_task.payload.get("dimensionValues") or [])
        for value_name in values:
            existing_value = _resolved_dimension_value_from_history(
                history,
                dimension_index=dimension_index,
                display_name=str(value_name),
            )
            if existing_value is not None:
                continue

            search_params = {
                "dimensionIndex": dimension_index,
                "count": 50,
                "fields": "id,displayName,dimensionIndex,active",
            }
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/accountingDimensionValue/search",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason=f"List existing values for accounting dimension {dimension_name} before creating {value_name}.",
                    method="GET",
                    path="/ledger/accountingDimensionValue/search",
                    params=search_params,
                )

            create_payload = {
                "displayName": value_name,
                "dimensionIndex": dimension_index,
                "active": True,
                "showInVoucherRegistration": True,
                "number": str(value_name),
            }
            if _has_attempt_exact_where(
                history,
                method="POST",
                path="/ledger/accountingDimensionValue",
                predicate=lambda request: _request_json_contains(request, create_payload),
            ):
                return None
            return _action(
                reason=f"Create accounting dimension value {value_name} on dimension {dimension_name}.",
                method="POST",
                path="/ledger/accountingDimensionValue",
                json=create_payload,
            )

        if not internal_task.payload.get("requiresVoucher"):
            return PlannerDecision(kind="finish", reason="The accounting dimension workflow is complete.")

        posting_account = internal_task.payload.get("postingAccount")
        counter_account = internal_task.payload.get("counterAccount")
        posting_amount = internal_task.payload.get("postingAmount")
        posting_dimension_value = internal_task.payload.get("postingDimensionValue")
        if posting_account in {None, ""} or counter_account in {None, ""} or posting_amount in {None, ""}:
            return None

        if posting_dimension_value in {None, ""}:
            return None
        dimension_value = _resolved_dimension_value_from_history(
            history,
            dimension_index=dimension_index,
            display_name=str(posting_dimension_value),
        )
        if dimension_value is None:
            return None

        account = _resolved_ledger_account_from_history(history, account_number=posting_account)
        if account is None:
            search_params = {"number": posting_account, "count": 10, "fields": "id,number,name"}
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/account",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the destination ledger account before creating the voucher.",
                    method="GET",
                    path="/ledger/account",
                    params=search_params,
                )
            return None

        offset = _resolved_ledger_account_from_history(history, account_number=counter_account)
        if offset is None:
            search_params = {"number": counter_account, "count": 10, "fields": "id,number,name"}
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/ledger/account",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the balancing counter account before creating the voucher.",
                    method="GET",
                    path="/ledger/account",
                    params=search_params,
                )
            return None

        currency_code = str(internal_task.payload.get("currencyCode") or "NOK")
        currency = _resolved_currency_from_history(history, code=currency_code)
        if currency is None:
            search_params = {"code": currency_code, "count": 5, "fields": "id,code"}
            if not _has_attempt_exact_where(
                history,
                method="GET",
                path="/currency",
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason="Resolve the voucher currency before creating the ledger voucher.",
                    method="GET",
                    path="/currency",
                    params=search_params,
                )
            return None

        voucher_payload = _build_ledger_dimension_voucher_payload(
            dimension_name=str(dimension_name),
            voucher_date=str(internal_task.payload.get("voucherDate") or ""),
            voucher_description=internal_task.payload.get("voucherDescription"),
            amount=float(posting_amount),
            account_id=account.get("id"),
            counter_account_id=offset.get("id"),
            currency_id=currency.get("id"),
            dimension_index=int(dimension_index),
            dimension_value_id=dimension_value.get("id"),
        )
        if _has_attempt_exact_where(
            history,
            method="POST",
            path="/ledger/voucher",
            predicate=lambda request: _request_json_contains(request, voucher_payload),
        ):
            return None
        return _action(
            reason="Create the balanced voucher with the resolved accounting dimension value on the requested posting line.",
            method="POST",
            path="/ledger/voucher",
            json=voucher_payload,
        )

    def _next_simple_upsert(
        self,
        *,
        internal_task: InternalTask,
        history: list[dict[str, Any]],
        resource_name: str,
        resource_path: str,
        resolver: Any,
        allowed_fields: tuple[str, ...],
    ) -> PlannerDecision | None:
        desired = dict(internal_task.payload)
        if not desired:
            return None

        entity = resolver(history, internal_task)
        if entity is None:
            search_params = _drop_empty(dict(internal_task.search))
            if search_params and not _has_attempt_exact_where(
                history,
                method="GET",
                path=resource_path,
                predicate=lambda request: _request_contains_params(request, search_params),
            ):
                return _action(
                    reason=f"Resolve the {resource_name} before mutating it or creating a duplicate.",
                    method="GET",
                    path=resource_path,
                    params=search_params,
                )
            if internal_task.operation == "update":
                return None
            if _has_attempt_exact_where(
                history,
                method="POST",
                path=resource_path,
                predicate=lambda request: _request_json_contains(request, desired),
            ):
                return None
            return _action(
                reason=f"Create the {resource_name} using the canonical OpenAPI fields.",
                method="POST",
                path=resource_path,
                json=desired,
            )

        if _entity_matches(entity, desired):
            return PlannerDecision(kind="finish", reason=f"The {resource_name} already satisfies the requested state.")

        entity_id = entity.get("id")
        if entity_id in {None, ""}:
            return None

        update_payload = _build_update_payload(entity, desired, allowed_fields=allowed_fields)
        if _has_attempt_exact_where(
            history,
            method="PUT",
            path=f"{resource_path}/{entity_id}",
            predicate=lambda request: _request_json_contains(request, update_payload),
        ):
            return None

        return _action(
            reason=f"Update the resolved {resource_name} to the requested state.",
            method="PUT",
            path=f"{resource_path}/{entity_id}",
            json=update_payload,
        )


def _action(
    *,
    reason: str,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json: Any | None = None,
) -> PlannerDecision:
    return PlannerDecision(
        kind="action",
        reason=reason,
        action=PlannedAction(
            method=method,
            path=path,
            params=params,
            json=json,
        ),
    )


def _request_contains_params(request: dict[str, Any], expected: dict[str, Any]) -> bool:
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return False
    return all(params.get(key) == value for key, value in expected.items())


def _request_json_contains(request: dict[str, Any], expected: dict[str, Any]) -> bool:
    return _entity_matches(request.get("json") or {}, expected)


def _entity_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for key, value in expected.items():
            if key not in actual:
                return False
            if not _entity_matches(actual.get(key), value):
                return False
        return True
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all(_entity_matches(left, right) for left, right in zip(actual, expected))
    return actual == expected


def _build_update_payload(
    current: dict[str, Any],
    desired: dict[str, Any],
    *,
    allowed_fields: tuple[str, ...],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": current.get("id"),
    }
    if current.get("version") not in {None, ""}:
        payload["version"] = current["version"]
    for field in allowed_fields:
        value = desired[field] if field in desired else current.get(field)
        if value in {None, ""}:
            continue
        payload[field] = value
    return payload


def _drop_empty(mapping: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in mapping.items():
        if _is_blank(value):
            continue
        if isinstance(value, dict):
            nested = _drop_empty(value)
            if nested:
                cleaned[key] = nested
            continue
        if isinstance(value, list):
            if value:
                cleaned[key] = value
            continue
        cleaned[key] = value
    return cleaned


def _generic_search_params(capability: ResourceCapability, search: dict[str, Any] | None) -> dict[str, Any]:
    raw_search = _drop_empty(dict(search or {}))
    if not raw_search:
        return {}
    allowed = set(capability.search_parameters) | {"count", "from", "fields", "sorting"}
    if capability.search_parameters:
        filtered = {key: value for key, value in raw_search.items() if key in allowed}
    else:
        filtered = dict(raw_search)
    if filtered and "count" not in filtered and capability.collection_path is not None:
        filtered["count"] = 10
    return filtered


def _generic_identity_ref(search: dict[str, Any] | None, payload: dict[str, Any] | None) -> dict[str, Any]:
    ref: dict[str, Any] = {}
    for source in (search or {}, payload or {}):
        for key, value in source.items():
            if isinstance(value, (dict, list)):
                continue
            if _is_blank(value):
                continue
            normalized = _normalized_generic_key(key)
            if normalized in {
                "id",
                "name",
                "title",
                "description",
                "number",
                "departmentnumber",
                "employeenumber",
                "productnumber",
                "projectnumber",
                "activitynumber",
                "invoicenumber",
                "organizationnumber",
                "customerorganizationnumber",
                "supplierorganizationnumber",
                "email",
                "employeeemail",
                "customeremail",
                "supplieremail",
                "customername",
                "suppliername",
                "projectname",
                "departmentname",
                "activityname",
                "productname",
                "code",
                "date",
            }:
                ref.setdefault(key, value)
    return ref


def _normalized_generic_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _generic_candidate_aliases(key: str) -> tuple[str, ...]:
    normalized = _normalized_generic_key(key)
    aliases = {
        "id": ("id",),
        "name": ("name", "title", "description"),
        "title": ("title", "name"),
        "description": ("description", "name", "title"),
        "customername": ("name",),
        "suppliername": ("name",),
        "projectname": ("name",),
        "departmentname": ("name",),
        "activityname": ("name",),
        "productname": ("name",),
        "number": ("number",),
        "departmentnumber": ("departmentNumber", "number"),
        "employeenumber": ("employeeNumber", "number"),
        "productnumber": ("number",),
        "projectnumber": ("number",),
        "activitynumber": ("number",),
        "invoicenumber": ("invoiceNumber", "number"),
        "organizationnumber": ("organizationNumber",),
        "customerorganizationnumber": ("organizationNumber",),
        "supplierorganizationnumber": ("organizationNumber",),
        "email": ("email", "invoiceEmail"),
        "employeeemail": ("email",),
        "customeremail": ("email", "invoiceEmail"),
        "supplieremail": ("email", "invoiceEmail"),
        "code": ("code",),
        "date": ("date",),
    }
    return aliases.get(normalized, (str(key),))


def _generic_entity_matches_ref(candidate: dict[str, Any], ref: dict[str, Any] | None) -> bool:
    if not ref:
        return True
    matched = False
    for key, value in ref.items():
        aliases = _generic_candidate_aliases(key)
        expected_text = _normalized_text_match(value)
        expected_raw = str(value)
        matched_this_key = False
        for alias in aliases:
            actual = candidate.get(alias)
            if isinstance(actual, dict):
                actual = actual.get("id")
            if actual in {None, ""}:
                continue
            if alias in {"id", "number", "departmentNumber", "employeeNumber", "invoiceNumber", "organizationNumber", "code"}:
                if str(actual) == expected_raw:
                    matched_this_key = True
                    break
            else:
                actual_text = _normalized_text_match(actual)
                if expected_text and actual_text and (expected_text == actual_text or expected_text in actual_text or actual_text in expected_text):
                    matched_this_key = True
                    break
        if matched_this_key:
            matched = True
            continue
        return False
    return matched


def _path_matches_template_path(template_path: str | None, actual_path: str) -> bool:
    if template_path in {None, ""}:
        return False
    pattern = re.sub(r"\{[^/]+\}", r"[^/]+", re.escape(str(template_path)).replace("\\{", "{").replace("\\}", "}"))
    return re.fullmatch(pattern, actual_path) is not None


def _render_detail_path(template_path: str | None, entity_id: Any) -> str | None:
    if template_path in {None, ""} or entity_id in {None, ""}:
        return None
    normalized_entity_id = str(entity_id)
    if "{" not in str(template_path):
        return str(template_path)
    return re.sub(r"\{[^/]+\}", normalized_entity_id, str(template_path))


def _resolved_resource_entity(
    history: list[dict[str, Any]],
    *,
    resource_family: str,
    collection_path: str | None,
    detail_path: str | None,
    ref: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if resource_family == "customer":
        return _resolved_customer_by_ref(history, ref)
    if resource_family == "supplier":
        return _resolved_supplier_by_ref(history, ref)
    if resource_family == "product":
        return _resolved_product_by_ref(history, ref)
    if resource_family == "employee":
        return _resolved_employee_by_ref(history, ref)
    if resource_family == "department":
        return _resolved_department_by_ref(history, ref)
    if resource_family == "project":
        return _resolved_project_by_ref(history, ref)
    if resource_family == "activity":
        return _resolved_activity_by_ref(history, ref)
    return _resolved_generic_entity(
        history,
        collection_path=collection_path,
        detail_path=detail_path,
        ref=ref,
    )


def _resolved_generic_entity(
    history: list[dict[str, Any]],
    *,
    collection_path: str | None,
    detail_path: str | None,
    ref: dict[str, Any] | None,
) -> dict[str, Any] | None:
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if collection_path and path == collection_path:
            if method in {"GET"} and isinstance(response.get("values"), list):
                candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
            elif method in {"POST", "PUT"} and isinstance(response.get("value"), dict):
                candidates = [response["value"]]
        elif detail_path and _path_matches_template_path(detail_path, path):
            if method in {"GET", "PUT"} and isinstance(response.get("value"), dict):
                candidates = [response["value"]]

        for candidate in candidates:
            if _generic_entity_matches_ref(candidate, ref):
                return candidate
        if len(candidates) == 1 and not ref:
            return candidates[0]
    return None


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _resolved_customer_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_org = ref.get("organizationNumber")
    target_name = ref.get("customerName") or ref.get("name")
    target_email = ref.get("email")

    target_org = str(target_org) if not _is_blank(target_org) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None
    target_email = str(target_email).lower() if not _is_blank(target_email) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/customer" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/customer" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/customer/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_org and str(candidate.get("organizationNumber")) == target_org:
                return candidate
            if target_email and str(candidate.get("email") or "").lower() == target_email:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_org, target_name, target_email)):
            return candidates[0]
    return None


def _resolved_supplier_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_org = ref.get("organizationNumber")
    target_name = ref.get("supplierName") or ref.get("name")
    target_email = ref.get("email") or ref.get("invoiceEmail")

    target_org = str(target_org) if not _is_blank(target_org) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None
    target_email = str(target_email).lower() if not _is_blank(target_email) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/supplier" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/supplier" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/supplier/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_org and str(candidate.get("organizationNumber")) == target_org:
                return candidate
            if target_email and str(candidate.get("email") or candidate.get("invoiceEmail") or "").lower() == target_email:
                return candidate
            if target_name and str(candidate.get("name") or candidate.get("displayName") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_org, target_name, target_email)):
            return candidates[0]
    return None


def _resolved_product_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_number = ref.get("productNumber") or ref.get("number")
    target_name = ref.get("name")
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/product" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/product" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/product/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_number and str(candidate.get("number")) == target_number:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_number, target_name)):
            return candidates[0]
    return None


def _resolved_vat_type_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_id = ref.get("id")
    target_number = ref.get("number") or ref.get("vatCode") or ref.get("code")
    target_name = ref.get("displayName") or ref.get("name")
    target_percentage = ref.get("percentage") or ref.get("vatRate") or ref.get("rate")

    target_id = str(target_id) if not _is_blank(target_id) else None
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None
    target_percentage = float(target_percentage) if target_percentage not in {None, ""} else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/ledger/vatType" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/ledger/vatType/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            candidate_id = candidate.get("id")
            if target_id and candidate_id not in {None, ""} and str(candidate_id) == target_id:
                return candidate
            if target_number and str(candidate.get("number") or "") == target_number:
                return candidate
            candidate_name = str(candidate.get("displayName") or candidate.get("name") or "").lower()
            if target_name and candidate_name == target_name:
                return candidate
            candidate_percentage = candidate.get("percentage")
            if target_percentage is not None and candidate_percentage not in {None, ""}:
                if float(candidate_percentage) == target_percentage:
                    return candidate
        if len(candidates) == 1 and not any((target_id, target_number, target_name, target_percentage is not None)):
            return candidates[0]
    return None


def _resolved_employee_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_email = ref.get("email")
    target_first = ref.get("firstName")
    target_last = ref.get("lastName")
    target_email = str(target_email).lower() if not _is_blank(target_email) else None
    target_first = str(target_first).lower() if not _is_blank(target_first) else None
    target_last = str(target_last).lower() if not _is_blank(target_last) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/employee" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/employee" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/employee/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_email and str(candidate.get("email") or "").lower() == target_email:
                return candidate
            if target_first and target_last:
                if (
                    str(candidate.get("firstName") or "").lower() == target_first
                    and str(candidate.get("lastName") or "").lower() == target_last
                ):
                    return candidate
        if len(candidates) == 1 and not any((target_email, target_first, target_last)):
            return candidates[0]
    return None


def _resolved_department_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_number = ref.get("departmentNumber")
    target_name = ref.get("name")
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/department" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/department" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/department/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_number and str(candidate.get("departmentNumber")) == target_number:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_number, target_name)):
            return candidates[0]
    return None


def _department_payload_from_ref(ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    payload = _drop_empty(
        {
            "name": ref.get("name"),
            "departmentNumber": ref.get("departmentNumber"),
        }
    )
    return payload or None


def _resolved_project_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_number = ref.get("number")
    target_name = ref.get("name")
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/project" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/project" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/project/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_number and str(candidate.get("number")) == target_number:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_number, target_name)):
            return candidates[0]
    return None


def _resolved_activity_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_number = ref.get("number")
    target_name = ref.get("name")
    target_number = str(target_number) if not _is_blank(target_number) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/activity" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/activity" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path == "/activity/>forTimeSheet" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/activity/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_number and str(candidate.get("number")) == target_number:
                return candidate
            if target_name and str(candidate.get("name") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_number, target_name)):
            return candidates[0]
    return None


def _resolved_employment_for_employee(history: list[dict[str, Any]], *, employee_id: Any) -> dict[str, Any] | None:
    target_employee_id = str(employee_id)
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/employee/employment" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/employee/employment" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/employee/employment/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            candidate_employee_id = _entity_id(candidate.get("employee"))
            if candidate_employee_id not in {None, ""} and str(candidate_employee_id) == target_employee_id:
                return candidate
        if len(candidates) == 1 and not target_employee_id:
            return candidates[0]
    return None


def _resolved_employment_details_for_employment(history: list[dict[str, Any]], *, employment_id: Any) -> dict[str, Any] | None:
    target_employment_id = str(employment_id)
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/employee/employment/details" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/employee/employment/details" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/employee/employment/details/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            candidate_employment_id = _entity_id(candidate.get("employment"))
            if candidate_employment_id not in {None, ""} and str(candidate_employment_id) == target_employment_id:
                return candidate
        if len(candidates) == 1 and not target_employment_id:
            return candidates[0]
    return None


def _resolved_occupation_code_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_id = ref.get("id")
    target_code = ref.get("code")
    target_name = ref.get("nameNO")
    target_id = str(target_id) if not _is_blank(target_id) else None
    target_code = str(target_code) if not _is_blank(target_code) else None
    target_name = str(target_name).lower() if not _is_blank(target_name) else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/employee/employment/occupationCode" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/employee/employment/occupationCode/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_id and str(candidate.get("id") or "") == target_id:
                return candidate
            if target_code and str(candidate.get("code") or "") == target_code:
                return candidate
            if target_name and str(candidate.get("nameNO") or "").lower() == target_name:
                return candidate
        if len(candidates) == 1 and not any((target_id, target_code, target_name)):
            return candidates[0]
    return None


def _resolved_timesheet_entry_from_history(
    history: list[dict[str, Any]],
    *,
    employee_id: Any,
    project_id: Any,
    activity_id: Any,
    entry_date: str,
) -> dict[str, Any] | None:
    target_employee_id = str(employee_id)
    target_project_id = str(project_id)
    target_activity_id = str(activity_id)
    target_date = str(entry_date)

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/timesheet/entry" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/timesheet/entry" and method == "GET" and isinstance(response.get("values"), list):
            params = request.get("params") or {}
            if (
                str(params.get("employeeId") or "") == target_employee_id
                and str(params.get("projectId") or "") == target_project_id
                and str(params.get("activityId") or "") == target_activity_id
                and str(params.get("dateFrom") or "") == target_date
                and str(params.get("dateTo") or "") == target_date
                and len(response["values"]) == 1
                and isinstance(response["values"][0], dict)
            ):
                return response["values"][0]
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/timesheet/entry/") and method in {"GET", "PUT"} and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if _timesheet_entry_identity_matches(
                candidate,
                employee_id=target_employee_id,
                project_id=target_project_id,
                activity_id=target_activity_id,
                entry_date=target_date,
            ):
                return candidate
    return None


def _timesheet_entry_identity_matches(
    entry: dict[str, Any],
    *,
    employee_id: str,
    project_id: str,
    activity_id: str,
    entry_date: str,
) -> bool:
    return (
        str(_entity_id(entry.get("employee"))) == employee_id
        and str(_entity_id(entry.get("project"))) == project_id
        and str(_entity_id(entry.get("activity"))) == activity_id
        and str(entry.get("date") or "") == entry_date
    )


def _timesheet_entry_matches(
    entry: dict[str, Any],
    *,
    entry_date: str,
    hours: Any,
    hourly_rate: Any,
    comment: Any,
) -> bool:
    target_hours = float(hours)
    if str(entry.get("date") or "") != str(entry_date):
        return False
    if float(entry.get("hours") or 0) != target_hours:
        return False
    chargeable_hours = entry.get("projectChargeableHours")
    if chargeable_hours not in {None, ""} and float(chargeable_hours) != target_hours:
        return False
    if not _is_blank(comment) and str(entry.get("comment") or "") != str(comment):
        return False
    return True


def _build_timesheet_entry_payload(
    *,
    employee_id: Any,
    project_id: Any,
    activity_id: Any,
    entry_date: str,
    hours: Any,
    hourly_rate: Any,
    comment: Any,
    entry_id: Any | None = None,
    entry_version: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "employee": {"id": employee_id},
        "project": {"id": project_id},
        "activity": {"id": activity_id},
        "date": entry_date,
        "hours": float(hours),
        "projectChargeableHours": float(hours),
    }
    if not _is_blank(comment):
        payload["comment"] = comment
    if entry_id not in {None, ""}:
        payload["id"] = entry_id
    if entry_version not in {None, ""}:
        payload["version"] = entry_version
    return payload


def _build_project_time_invoice_order_payload(
    *,
    customer_id: Any,
    project_id: Any,
    order_date: str,
    hours: Any,
    hourly_rate: Any,
    activity_name: Any,
    project_name: Any,
) -> dict[str, Any]:
    description_parts = [str(activity_name).strip() if not _is_blank(activity_name) else ""]
    if not _is_blank(project_name):
        description_parts.append(f"Project: {project_name}")
    description = " - ".join(part for part in description_parts if part)
    if not description:
        description = "Project hours"
    return {
        "customer": {"id": customer_id},
        "project": {"id": project_id},
        "orderDate": order_date,
        "deliveryDate": order_date,
        "orderLines": [
            {
                "description": description,
                "count": float(hours),
                "unitPriceExcludingVatCurrency": float(hourly_rate),
            }
        ],
    }


def _build_invoice_payload_from_order(
    *,
    order_id: Any,
    customer_id: Any,
    invoice_date: Any,
    invoice_due_date: Any,
) -> dict[str, Any]:
    return _drop_empty(
        {
            "invoiceDate": invoice_date,
            "invoiceDueDate": invoice_due_date or invoice_date,
            "customer": {"id": customer_id},
            "orders": [{"id": order_id}],
        }
    )


def _build_incoming_invoice_payload_from_internal(
    internal_task: InternalTask,
    *,
    supplier: dict[str, Any],
    account: dict[str, Any],
    vat_type: dict[str, Any] | None,
    voucher_type_id: Any | None,
) -> dict[str, Any] | None:
    supplier_id = supplier.get("id")
    account_id = account.get("id")
    amount_including_vat = internal_task.payload.get("amountIncludingVat")
    if supplier_id in {None, ""} or account_id in {None, ""} or amount_including_vat in {None, ""}:
        return None

    normalized_amount = round(abs(float(amount_including_vat)), 2)
    invoice_number = internal_task.payload.get("invoiceNumber")
    description = str(
        internal_task.payload.get("description")
        or invoice_number
        or "Supplier invoice"
    ).strip()
    if not description:
        description = "Supplier invoice"

    invoice_date = str(internal_task.payload.get("invoiceDate") or date.today().isoformat())
    due_date = str(internal_task.payload.get("dueDate") or invoice_date)

    invoice_header = {
        "vendorId": supplier_id,
        "invoiceDate": invoice_date,
        "dueDate": due_date,
        "invoiceAmount": normalized_amount,
        "description": description,
    }
    if invoice_number not in {None, ""}:
        invoice_header["invoiceNumber"] = invoice_number
    if voucher_type_id not in {None, ""}:
        invoice_header["voucherTypeId"] = voucher_type_id

    order_line = {
        "row": 1,
        "externalId": _incoming_invoice_external_id(
            supplier_id=supplier_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            description=description,
        ),
        "description": description,
        "accountId": account_id,
        "count": 1,
        "amountInclVat": normalized_amount,
    }
    if isinstance(vat_type, dict) and vat_type.get("id") not in {None, ""}:
        order_line["vatTypeId"] = vat_type["id"]
    elif account.get("vatTypeId") not in {None, ""}:
        order_line["vatTypeId"] = account["vatTypeId"]

    return {
        "invoiceHeader": invoice_header,
        "orderLines": [order_line],
    }


def _salary_line_type_ref(line: dict[str, Any]) -> dict[str, Any]:
    salary_type = line.get("salaryType") if isinstance(line.get("salaryType"), dict) else {}
    return _drop_empty(
        {
            "id": line.get("salaryTypeId") or salary_type.get("id"),
            "number": line.get("salaryTypeNumber") or line.get("typeNumber") or salary_type.get("number"),
            "name": line.get("salaryTypeName") or line.get("typeName") or salary_type.get("name"),
            "description": line.get("salaryTypeDescription") or salary_type.get("description"),
        }
    )


def _resolved_salary_type_by_ref(history: list[dict[str, Any]], ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref:
        return None
    target_id = ref.get("id")
    target_number = ref.get("number")
    target_name = _normalized_text_match(ref.get("name"))
    target_description = _normalized_text_match(ref.get("description"))
    target_id = str(target_id) if target_id not in {None, ""} else None
    target_number = str(target_number) if target_number not in {None, ""} else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/salary/type" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/salary/type/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if target_id and str(candidate.get("id") or "") == target_id:
                return candidate
            if target_number and str(candidate.get("number") or "") == target_number:
                return candidate
            candidate_name = _normalized_text_match(candidate.get("name"))
            if target_name and candidate_name and (target_name == candidate_name or target_name in candidate_name or candidate_name in target_name):
                return candidate
            candidate_description = _normalized_text_match(candidate.get("description"))
            if (
                target_description
                and candidate_description
                and (
                    target_description == candidate_description
                    or target_description in candidate_description
                    or candidate_description in target_description
                )
            ):
                return candidate
        if len(candidates) == 1 and not any((target_id, target_number, target_name, target_description)):
            return candidates[0]
    return None


def _salary_type_search_params(ref: dict[str, Any] | None) -> dict[str, Any]:
    if not ref:
        return {}
    return _drop_empty(
        {
            "id": ref.get("id"),
            "number": ref.get("number"),
            "name": ref.get("name"),
            "description": ref.get("description"),
            "count": 20,
            "fields": "id,number,name,description",
        }
    )


def _build_salary_transaction_payload(
    *,
    internal_task: InternalTask,
    employee_id: Any,
    salary_types: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if employee_id in {None, ""}:
        return None
    payroll_date = internal_task.payload.get("date") or date.today().isoformat()
    payroll_month = internal_task.payload.get("month")
    payroll_year = internal_task.payload.get("year")
    salary_lines = [line for line in (internal_task.payload.get("salaryLines") or []) if isinstance(line, dict)]
    if not salary_lines or len(salary_lines) != len(salary_types):
        return None

    specifications: list[dict[str, Any]] = []
    for line, salary_type in zip(salary_lines, salary_types):
        salary_type_id = salary_type.get("id")
        if salary_type_id in {None, ""}:
            return None
        specification = _drop_empty(
            {
                "employee": {"id": employee_id},
                "salaryType": {"id": salary_type_id},
                "year": int(payroll_year) if payroll_year not in {None, ""} else None,
                "month": int(payroll_month) if payroll_month not in {None, ""} else None,
                "amount": _safe_float(line.get("amount")),
                "rate": _safe_float(line.get("rate")),
                "count": _safe_float(line.get("count")),
                "description": line.get("description"),
            }
        )
        if not any(key in specification for key in ("amount", "rate", "count")):
            return None
        specifications.append(specification)

    return _drop_empty(
        {
            "date": payroll_date,
            "year": int(payroll_year) if payroll_year not in {None, ""} else None,
            "month": int(payroll_month) if payroll_month not in {None, ""} else None,
            "isHistorical": internal_task.payload.get("isHistorical"),
            "paySlipsAvailableDate": internal_task.payload.get("paySlipsAvailableDate"),
            "payslips": [
                _drop_empty(
                    {
                        "employee": {"id": employee_id},
                        "date": payroll_date,
                        "year": int(payroll_year) if payroll_year not in {None, ""} else None,
                        "month": int(payroll_month) if payroll_month not in {None, ""} else None,
                        "specifications": specifications,
                    }
                )
            ],
        }
    )


def _bank_statement_direction(entry: dict[str, Any]) -> str:
    raw_direction = _normalized_text_match(entry.get("direction"))
    if raw_direction in {"incoming", "credit", "customer", "in"}:
        return "incoming"
    if raw_direction in {"outgoing", "debit", "supplier", "out"}:
        return "outgoing"
    amount = _safe_float(entry.get("amount"))
    if amount is not None:
        return "outgoing" if amount < 0 else "incoming"
    if isinstance(entry.get("supplier"), dict) and entry["supplier"]:
        return "outgoing"
    return "incoming"


def _bank_entry_paid_amount(entry: dict[str, Any]) -> float | None:
    amount = _safe_float(
        entry.get("amount")
        or entry.get("amountCurrency")
        or entry.get("paidAmount")
        or entry.get("paymentAmount")
    )
    if amount is None:
        return None
    return round(abs(amount), 2)


def _resolved_bank_customer_invoice_from_history(
    history: list[dict[str, Any]],
    *,
    entry: dict[str, Any],
    customer_id: Any | None,
) -> dict[str, Any] | None:
    target_invoice_number = str(entry.get("invoiceNumber")) if entry.get("invoiceNumber") not in {None, ""} else None
    target_customer_id = str(customer_id) if customer_id not in {None, ""} else None
    target_amount = _bank_entry_paid_amount(entry)
    target_description = _normalized_text_match(entry.get("description"))
    matches: list[dict[str, Any]] = []

    for history_entry in reversed(history):
        response = history_entry.get("response")
        if not isinstance(response, dict):
            continue
        request = history_entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/invoice":
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        if target_invoice_number:
            for candidate in values:
                if str(candidate.get("invoiceNumber") or "") == target_invoice_number:
                    return candidate
        for candidate in values:
            candidate_customer_id = _entity_id(candidate.get("customer")) or candidate.get("customerId")
            if target_customer_id and str(candidate_customer_id or "") not in {target_customer_id, ""}:
                continue
            if target_amount is not None and not _invoice_candidate_matches_amount(candidate, target_amount):
                continue
            if target_description and not _invoice_candidate_matches_description(candidate, target_description):
                continue
            matches.append(candidate)
        if len(values) == 1 and not any((target_invoice_number, target_customer_id, target_amount is not None)):
            return values[0]

    if len(matches) == 1:
        return matches[0]
    return None


def _bank_customer_invoice_search_params(
    *,
    entry: dict[str, Any],
    customer_id: Any | None,
    internal_task: InternalTask,
    task_analysis: TaskAnalysis,
) -> dict[str, Any] | None:
    invoice_number = entry.get("invoiceNumber")
    date_from = entry.get("invoiceDateFrom") or internal_task.payload.get("fromDate") or internal_task.search.get("fromDate")
    date_to = entry.get("invoiceDateTo") or internal_task.payload.get("toDate") or internal_task.search.get("toDate")
    if date_from in {None, ""} or date_to in {None, ""}:
        fallback_from, fallback_to = best_effort_date_window(
            task_analysis,
            start_key="fromDate",
            end_key="toDate",
        )
        date_from = date_from or fallback_from
        date_to = date_to or fallback_to
    params = _drop_empty(
        {
            "invoiceDateFrom": date_from,
            "invoiceDateTo": date_to,
            "invoiceNumber": invoice_number,
            "customerId": customer_id,
            "count": 50,
            "fields": "id,invoiceNumber,amount,amountCurrency,amountExcludingVat,amountExcludingVatCurrency,invoiceDate,invoiceComment,invoiceRemarks,customer(id),orderLines(description)",
        }
    )
    if not any(key in params for key in ("invoiceNumber", "customerId")):
        return None
    return params


def _resolved_bank_supplier_invoice_from_history(
    history: list[dict[str, Any]],
    *,
    entry: dict[str, Any],
    supplier_id: Any | None,
) -> dict[str, Any] | None:
    target_invoice_number = str(entry.get("invoiceNumber")) if entry.get("invoiceNumber") not in {None, ""} else None
    target_supplier_id = str(supplier_id) if supplier_id not in {None, ""} else None
    target_amount = _bank_entry_paid_amount(entry)
    matches: list[dict[str, Any]] = []

    for history_entry in reversed(history):
        response = history_entry.get("response")
        if not isinstance(response, dict):
            continue
        request = history_entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        values: list[dict[str, Any]] = []
        if method == "GET" and path == "/incomingInvoice/search" and isinstance(response.get("values"), list):
            values = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif method == "POST" and path == "/incomingInvoice" and isinstance(response.get("value"), dict):
            values = [response["value"]]
        elif method == "GET" and path.startswith("/incomingInvoice/") and isinstance(response.get("value"), dict):
            values = [response["value"]]
        if not values:
            continue
        if target_invoice_number:
            for candidate in values:
                if str(candidate.get("invoiceNumber") or "") == target_invoice_number:
                    return candidate
        for candidate in values:
            candidate_supplier_id = (
                _entity_id(candidate.get("vendor"))
                or candidate.get("vendorId")
                or _entity_id(candidate.get("supplier"))
            )
            if target_supplier_id and str(candidate_supplier_id or "") not in {target_supplier_id, ""}:
                continue
            candidate_amount = _safe_float(
                candidate.get("remainingAmount")
                or candidate.get("invoiceAmount")
                or candidate.get("amount")
                or candidate.get("amountCurrency")
            )
            if target_amount is not None and candidate_amount is not None and round(abs(candidate_amount), 2) != round(target_amount, 2):
                if candidate_amount < target_amount:
                    continue
            matches.append(candidate)
        if len(values) == 1 and not any((target_invoice_number, target_supplier_id, target_amount is not None)):
            return values[0]

    if len(matches) == 1:
        return matches[0]
    return None


def _bank_supplier_invoice_search_params(
    *,
    entry: dict[str, Any],
    supplier_id: Any | None,
    internal_task: InternalTask,
    task_analysis: TaskAnalysis,
) -> dict[str, Any] | None:
    invoice_number = entry.get("invoiceNumber")
    date_from = entry.get("invoiceDateFrom") or internal_task.payload.get("fromDate") or internal_task.search.get("fromDate")
    date_to = entry.get("invoiceDateTo") or internal_task.payload.get("toDate") or internal_task.search.get("toDate")
    if date_from in {None, ""} or date_to in {None, ""}:
        fallback_from, fallback_to = best_effort_date_window(
            task_analysis,
            start_key="fromDate",
            end_key="toDate",
        )
        date_from = date_from or fallback_from
        date_to = date_to or fallback_to
    params = _drop_empty(
        {
            "invoiceDateFrom": date_from,
            "invoiceDateTo": date_to,
            "invoiceNumber": invoice_number,
            "vendorId": supplier_id,
            "count": 50,
            "fields": "voucherId,invoiceNumber,invoiceAmount,amountCurrency,remainingAmount,vendor(id,name,organizationNumber)",
        }
    )
    if not any(key in params for key in ("invoiceNumber", "vendorId")):
        return None
    return params


def _bank_supplier_partial_payment(entry: dict[str, Any], *, incoming_invoice: dict[str, Any]) -> bool:
    explicit = entry.get("partialPayment")
    if isinstance(explicit, bool):
        return explicit
    paid_amount = _bank_entry_paid_amount(entry)
    if paid_amount is None:
        return False
    remaining_amount = _safe_float(incoming_invoice.get("remainingAmount"))
    if remaining_amount is not None:
        return round(paid_amount, 2) < round(abs(remaining_amount), 2)
    invoice_amount = _safe_float(
        incoming_invoice.get("invoiceAmount")
        or incoming_invoice.get("amount")
        or incoming_invoice.get("amountCurrency")
    )
    if invoice_amount is not None:
        return round(paid_amount, 2) < round(abs(invoice_amount), 2)
    return False


def _vat_type_lookup_params(
    order_lines: list[dict[str, Any]],
    *,
    vat_date: Any | None,
) -> dict[str, Any] | None:
    if not any(isinstance(line.get("vatType"), dict) for line in order_lines):
        return None
    return _drop_empty(
        {
            "typeOfVat": "OUTGOING",
            "vatDate": vat_date,
            "count": 100,
            "fields": "id,name,displayName,number,percentage",
        }
    )


def _all_order_line_vat_types_resolved(history: list[dict[str, Any]], order_lines: list[dict[str, Any]]) -> bool:
    for line in order_lines:
        vat_type_ref = line.get("vatType")
        if not isinstance(vat_type_ref, dict):
            continue
        resolved = _resolved_vat_type_by_ref(history, vat_type_ref)
        if resolved is None or resolved.get("id") in {None, ""}:
            return False
    return True


def _resolved_customer_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_customer_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_supplier_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_supplier_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_product_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_product_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_employee_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_employee_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_department_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_department_by_ref(history, internal_task.search or internal_task.payload)


def _resolved_project_from_internal(history: list[dict[str, Any]], internal_task: InternalTask) -> dict[str, Any] | None:
    return _resolved_project_by_ref(history, internal_task.search or internal_task.payload)


def _product_payload_from_order_line(line: dict[str, Any]) -> dict[str, Any] | None:
    product_number = line.get("productNumber")
    description = line.get("description")
    if _is_blank(product_number) or _is_blank(description):
        return None
    payload = {
        "name": description,
        "number": product_number,
    }
    if line.get("unitPriceExcludingVatCurrency") not in {None, ""}:
        payload["priceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
    return payload


def _build_order_payload_from_internal(
    internal_task: InternalTask,
    *,
    customer: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    customer_id = customer.get("id")
    if customer_id in {None, ""}:
        return None

    order_lines: list[dict[str, Any]] = []
    for line in internal_task.payload.get("orderLines") or []:
        product_number = line.get("productNumber")
        product = None
        if not _is_blank(product_number):
            product = _resolved_product_by_ref(
                history,
                {"productNumber": product_number, "name": line.get("description")},
            )
            if product is None or product.get("id") in {None, ""}:
                return None
        if product is None and _is_blank(line.get("description")):
            return None
        order_line = {"count": line.get("count") or 1}
        if product is not None:
            order_line["product"] = {"id": product["id"]}
        if not _is_blank(line.get("description")):
            order_line["description"] = line["description"]
        vat_type_ref = line.get("vatType")
        if isinstance(vat_type_ref, dict):
            vat_type = _resolved_vat_type_by_ref(history, vat_type_ref)
            if vat_type is None or vat_type.get("id") in {None, ""}:
                return None
            order_line["vatType"] = {"id": vat_type["id"]}
        if line.get("unitPriceExcludingVatCurrency") not in {None, ""}:
            order_line["unitPriceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
        order_lines.append(order_line)

    if not order_lines:
        return None

    payload: dict[str, Any] = {
        "customer": {"id": customer_id},
        "orderDate": internal_task.payload.get("orderDate"),
        "deliveryDate": internal_task.payload.get("deliveryDate") or internal_task.payload.get("orderDate"),
        "orderLines": order_lines,
    }
    project = internal_task.payload.get("project")
    if isinstance(project, dict) and project.get("id") not in {None, ""}:
        payload["project"] = {"id": project["id"]}
    return payload


def _sales_total_amount(internal_task: InternalTask, *, history: list[dict[str, Any]] | None = None) -> float | None:
    total = 0.0
    order_lines = list(internal_task.payload.get("orderLines") or [])
    if not order_lines:
        return None
    for line in order_lines:
        unit_price = line.get("unitPriceExcludingVatCurrency")
        if unit_price in {None, ""}:
            return None
        vat_percentage = None
        vat_type_ref = line.get("vatType")
        if isinstance(vat_type_ref, dict):
            vat_percentage = vat_type_ref.get("percentage")
            if vat_percentage in {None, ""} and history is not None:
                resolved_vat_type = _resolved_vat_type_by_ref(history, vat_type_ref)
                if resolved_vat_type is not None:
                    vat_percentage = resolved_vat_type.get("percentage")
        multiplier = 1.0
        if vat_percentage not in {None, ""}:
            multiplier += float(vat_percentage) / 100.0
        total += float(unit_price) * float(line.get("count") or 1) * multiplier
    return total


def _resolved_dimension_name_from_history(
    history: list[dict[str, Any]],
    *,
    dimension_name: str,
) -> dict[str, Any] | None:
    target = dimension_name.lower()
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/ledger/accountingDimensionName" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/ledger/accountingDimensionName" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/ledger/accountingDimensionName/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if str(candidate.get("dimensionName") or "").lower() == target:
                return candidate
    return None


def _resolved_dimension_value_from_history(
    history: list[dict[str, Any]],
    *,
    dimension_index: Any,
    display_name: str,
) -> dict[str, Any] | None:
    target_name = display_name.lower()
    target_index = str(dimension_index)
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/ledger/accountingDimensionValue" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/ledger/accountingDimensionValue/search" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/ledger/accountingDimensionValue/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if str(candidate.get("dimensionIndex")) != target_index:
                continue
            if str(candidate.get("displayName") or "").lower() == target_name:
                return candidate
    return None


def _resolved_ledger_account_from_history(
    history: list[dict[str, Any]],
    *,
    account_number: Any,
) -> dict[str, Any] | None:
    target_number = str(account_number)
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/ledger/account" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path == "/ledger/account" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/ledger/account/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if str(candidate.get("number")) == target_number:
                return candidate
    return None


def _resolved_default_supplier_invoice_account(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred_numbers = ("6500", "4300", "4000", "4500")
    fallback: dict[str, Any] | None = None
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/ledger/account":
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        for candidate in values:
            if candidate.get("isApplicableForSupplierInvoice") is not True:
                continue
            if str(candidate.get("number") or "") in preferred_numbers:
                return candidate
            if fallback is None:
                fallback = candidate
    return fallback


def _payment_reversal_posting_search_params(
    task_analysis: TaskAnalysis,
    *,
    customer_id: Any,
    include_type: bool = True,
) -> dict[str, Any]:
    date_from, date_to = best_effort_date_window(
        task_analysis,
        start_key="paymentDateFrom",
        end_key="paymentDateTo",
    )
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "customerId": customer_id,
        "count": 200,
        "fields": "id,date,type,invoiceNumber,description,amount,voucher(id,description,date,version)",
    }
    if include_type:
        params["type"] = "INCOMING_PAYMENT"
    return _drop_empty(params)


def _resolved_payment_reversal_posting(
    history: list[dict[str, Any]],
    *,
    invoice: dict[str, Any],
    internal_task: InternalTask,
) -> dict[str, Any] | None:
    target_invoice_number = invoice.get("invoiceNumber") or internal_task.payload.get("invoiceNumber")
    target_invoice_number = str(target_invoice_number) if target_invoice_number not in {None, ""} else None
    target_description = _normalized_text_match(
        internal_task.payload.get("description")
        or invoice.get("invoiceComment")
        or invoice.get("invoiceRemarks")
    )
    target_amount = _safe_float(
        internal_task.payload.get("amountExcludingVat")
        or invoice.get("amountExcludingVat")
        or internal_task.payload.get("amount")
        or invoice.get("amount")
    )
    candidates: list[tuple[int, dict[str, Any]]] = []

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/ledger/posting":
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        for candidate in values:
            score = 0
            candidate_invoice_number = candidate.get("invoiceNumber")
            if target_invoice_number and str(candidate_invoice_number or "") == target_invoice_number:
                score += 100
            description_fields = [
                candidate.get("description"),
                (candidate.get("voucher") or {}).get("description") if isinstance(candidate.get("voucher"), dict) else None,
            ]
            if target_description and any(
                target_description in normalized or normalized in target_description
                for normalized in (_normalized_text_match(value) for value in description_fields)
                if normalized
            ):
                score += 10
            candidate_amount = _safe_float(candidate.get("amount"))
            if target_amount is not None and candidate_amount is not None:
                if round(abs(candidate_amount), 2) == round(abs(target_amount), 2):
                    score += 5
            if _entity_id(candidate.get("voucher")) not in {None, ""}:
                score += 1
            if score > 0:
                candidates.append((score, candidate))
        if len(values) == 1 and not any((target_invoice_number, target_description, target_amount is not None)):
            return values[0]

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    top_score = candidates[0][0]
    top_candidates = [candidate for score, candidate in candidates if score == top_score]
    if len(top_candidates) == 1:
        return top_candidates[0]
    for candidate in top_candidates:
        if _entity_id(candidate.get("voucher")) not in {None, ""}:
            return candidate
    return top_candidates[0]


def _project_lifecycle_order_lines(
    *,
    project_name: Any,
    timesheet_entries: list[dict[str, Any]],
    budget_amount: Any,
) -> list[dict[str, Any]]:
    normalized_budget = _safe_float(budget_amount)
    if normalized_budget not in {None, 0.0}:
        name = str(project_name or "Project").strip() or "Project"
        return [
            {
                "description": f"{name} project budget",
                "count": 1,
                "unitPriceExcludingVatCurrency": round(float(normalized_budget), 2),
            }
        ]

    order_lines: list[dict[str, Any]] = []
    for entry in timesheet_entries:
        hours = _safe_float(entry.get("hours"))
        hourly_rate = _safe_float(entry.get("hourlyRate"))
        if hours in {None, 0.0}:
            continue
        if hourly_rate is None:
            return []

        employee_ref = entry.get("employeeRef") if isinstance(entry.get("employeeRef"), dict) else {}
        employee_name = " ".join(
            part
            for part in (
                str((employee_ref or {}).get("firstName") or "").strip(),
                str((employee_ref or {}).get("lastName") or "").strip(),
            )
            if part
        )
        description_parts = [str(project_name or "Project work").strip() or "Project work"]
        if employee_name:
            description_parts.append(employee_name)
        if not _is_blank(entry.get("comment")):
            description_parts.append(str(entry.get("comment")).strip())
        order_lines.append(
            {
                "description": " - ".join(part for part in description_parts if part),
                "count": float(hours),
                "unitPriceExcludingVatCurrency": float(hourly_rate),
            }
        )
    return order_lines


def _resolved_currency_from_history(history: list[dict[str, Any]], *, code: str) -> dict[str, Any] | None:
    target_code = str(code).upper()
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/currency" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path.startswith("/currency/") and method == "GET" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if str(candidate.get("code") or "").upper() == target_code:
                return candidate
    return None


def _build_ledger_dimension_voucher_payload(
    *,
    dimension_name: str,
    voucher_date: str,
    voucher_description: Any,
    amount: float,
    account_id: Any,
    counter_account_id: Any,
    currency_id: Any,
    dimension_index: int,
    dimension_value_id: Any,
) -> dict[str, Any]:
    normalized_date = voucher_date or date.today().isoformat()
    normalized_description = str(voucher_description or f"Manual voucher for {dimension_name}").strip()
    absolute_amount = round(abs(float(amount)), 2)
    dimension_key = f"freeAccountingDimension{dimension_index}"
    posting_with_dimension = {
        "date": normalized_date,
        "description": normalized_description,
        "account": {"id": account_id},
        "currency": {"id": currency_id},
        "amountGross": absolute_amount,
        "amountGrossCurrency": absolute_amount,
        dimension_key: {"id": dimension_value_id},
    }
    balancing_posting = {
        "date": normalized_date,
        "description": normalized_description,
        "account": {"id": counter_account_id},
        "currency": {"id": currency_id},
        "amountGross": -absolute_amount,
        "amountGrossCurrency": -absolute_amount,
    }
    return {
        "date": normalized_date,
        "description": normalized_description,
        "postings": [posting_with_dimension, balancing_posting],
    }


def _travel_expense_cost_category_search_params(description: Any) -> dict[str, Any]:
    return {
        "query": _travel_cost_category_query(description),
        "showOnEmployeeExpenses": True,
        "count": 20,
        "fields": "id,description,displayName,showOnEmployeeExpenses",
    }


def _travel_expense_lookup_params(*, employee_id: Any, internal_task: InternalTask) -> dict[str, Any]:
    params = _drop_empty(
        {
            "employeeId": employee_id,
            "title": internal_task.payload.get("title"),
            "departureDateFrom": (internal_task.payload.get("travelDetails") or {}).get("departureDate"),
            "returnDateTo": (internal_task.payload.get("travelDetails") or {}).get("returnDate"),
            "count": 20,
            "fields": "id,version,title,travelDetails,employee(id)",
        }
    )
    if "departureDateFrom" not in params and internal_task.search.get("departureDate") not in {None, ""}:
        params["departureDateFrom"] = internal_task.search.get("departureDate")
    if "returnDateTo" not in params and internal_task.search.get("returnDate") not in {None, ""}:
        params["returnDateTo"] = internal_task.search.get("returnDate")
    return params


def _resolved_travel_expense_from_history(
    history: list[dict[str, Any]],
    *,
    employee_id: Any,
    internal_task: InternalTask,
) -> dict[str, Any] | None:
    target_employee_id = str(employee_id)
    target_title = _normalized_text_match(internal_task.payload.get("title"))
    target_departure = (
        (internal_task.payload.get("travelDetails") or {}).get("departureDate")
        or internal_task.search.get("departureDate")
    )
    target_return = (
        (internal_task.payload.get("travelDetails") or {}).get("returnDate")
        or internal_task.search.get("returnDate")
    )

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        candidates: list[dict[str, Any]] = []
        if path == "/travelExpense" and method == "GET" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif path == "/travelExpense" and method == "POST" and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        elif path.startswith("/travelExpense/") and method in {"GET", "PUT"} and isinstance(response.get("value"), dict):
            candidates = [response["value"]]

        for candidate in candidates:
            if str(_entity_id(candidate.get("employee"))) != target_employee_id:
                continue
            candidate_title = _normalized_text_match(candidate.get("title"))
            if target_title and candidate_title and target_title != candidate_title:
                continue
            travel_details = candidate.get("travelDetails") if isinstance(candidate.get("travelDetails"), dict) else {}
            if target_departure not in {None, ""} and str(travel_details.get("departureDate") or "") != str(target_departure):
                continue
            if target_return not in {None, ""} and str(travel_details.get("returnDate") or "") != str(target_return):
                continue
            return candidate
        if len(candidates) == 1 and not any((target_title, target_departure, target_return)):
            candidate = candidates[0]
            if str(_entity_id(candidate.get("employee"))) == target_employee_id:
                return candidate
    return None


def _travel_cost_category_query(description: Any) -> str:
    normalized = _normalized_text_match(description) or ""
    keyword_map = (
        (("flight", "flug", "fly", "airfare", "ticket", "billett"), "flight"),
        (("taxi", "cab"), "taxi"),
        (("hotel", "lodging", "overnight"), "hotel"),
        (("parking", "parkering"), "parking"),
        (("train", "rail", "tog"), "train"),
        (("meal", "restaurant", "food", "mat"), "meal"),
    )
    for keywords, query in keyword_map:
        if any(keyword in normalized for keyword in keywords):
            return query
    return str(description or "").strip()


def _resolved_travel_payment_type_from_history(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/travelExpense/paymentType":
            continue
        params = request.get("params") or {}
        if params.get("showOnEmployeeExpenses") is not True:
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        if values:
            return values[0]
    return None


def _resolved_travel_cost_category_from_history(
    history: list[dict[str, Any]],
    *,
    query: Any,
    description: Any,
) -> dict[str, Any] | None:
    target_query = _normalized_text_match(query)
    target_description = _normalized_text_match(description)
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/travelExpense/costCategory":
            continue
        params = request.get("params") or {}
        if params.get("showOnEmployeeExpenses") is not True:
            continue
        if target_query and _normalized_text_match(params.get("query")) != target_query:
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        for candidate in values:
            candidate_labels = (
                _normalized_text_match(candidate.get("description")),
                _normalized_text_match(candidate.get("displayName")),
            )
            if target_description and any(
                label and (target_description in label or label in target_description) for label in candidate_labels
            ):
                return candidate
            if target_query and any(label and (target_query in label or label in target_query) for label in candidate_labels):
                return candidate
        if len(values) == 1:
            return values[0]
    return None


def _build_travel_expense_payload(
    *,
    internal_task: InternalTask,
    employee_id: Any,
    payment_type_id: Any | None,
    resolved_cost_categories: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if employee_id in {None, ""}:
        return None
    payload = dict(internal_task.payload)
    travel_details = dict(payload.get("travelDetails") or {})
    title = payload.get("title")
    if not travel_details or title in {None, ""}:
        return None

    normalized_costs: list[dict[str, Any]] = []
    source_costs = [item for item in (payload.get("costs") or []) if isinstance(item, dict)]
    for cost, category in zip(source_costs, resolved_cost_categories):
        category_id = category.get("id")
        amount = _safe_float(cost.get("amount"))
        if category_id in {None, ""} or amount is None:
            return None
        cost_payload = _drop_empty(
            {
                "date": cost.get("date") or travel_details.get("departureDate"),
                "comments": cost.get("description"),
                "amountCurrencyIncVat": round(amount, 2),
                "costCategory": {"id": category_id},
                "paymentType": {"id": payment_type_id} if payment_type_id not in {None, ""} else None,
            }
        )
        normalized_costs.append(cost_payload)

    per_diems: list[dict[str, Any]] = []
    for item in payload.get("perDiemCompensations") or []:
        if not isinstance(item, dict):
            continue
        per_diems.append(_drop_empty(dict(item)))

    return _drop_empty(
        {
            "employee": {"id": employee_id},
            "title": title,
            "travelDetails": travel_details,
            "perDiemCompensations": per_diems,
            "costs": normalized_costs,
        }
    )


def _first_unresolved_month_end_account_number(
    history: list[dict[str, Any]],
    *,
    voucher_spec: dict[str, Any],
) -> str | None:
    for posting in voucher_spec.get("postings") or []:
        if not isinstance(posting, dict):
            continue
        account_number = posting.get("accountNumber")
        if account_number in {None, ""}:
            return None
        resolved = _resolved_ledger_account_from_history(history, account_number=account_number)
        if resolved is None or resolved.get("id") in {None, ""}:
            return str(account_number)
    return None


def _build_month_end_voucher_payload(
    *,
    voucher_date: str,
    voucher_spec: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    description = str(voucher_spec.get("description") or "Month-end voucher").strip()
    if not description:
        description = "Month-end voucher"
    postings_payload: list[dict[str, Any]] = []
    for row_number, posting in enumerate(voucher_spec.get("postings") or [], start=1):
        if not isinstance(posting, dict):
            continue
        account_number = posting.get("accountNumber")
        account = _resolved_ledger_account_from_history(history, account_number=account_number)
        amount = _safe_float(posting.get("amount"))
        if account is None or account.get("id") in {None, ""} or amount is None:
            return None
        postings_payload.append(
            {
                "row": row_number,
                "date": voucher_date,
                "description": description,
                "account": {"id": account["id"]},
                "amountGross": round(amount, 2),
                "amountGrossCurrency": round(amount, 2),
            }
        )
    if not postings_payload:
        return None
    return {
        "date": voucher_date,
        "description": description,
        "postings": postings_payload,
    }


def _entity_id(value: Any) -> Any | None:
    if isinstance(value, dict):
        return value.get("id")
    return value


def _credit_note_invoice_search_params(
    task_analysis: TaskAnalysis,
    *,
    customer_id: Any,
    invoice_number: Any | None,
) -> dict[str, Any]:
    date_from, date_to = best_effort_date_window(
        task_analysis,
        start_key="invoiceDateFrom",
        end_key="invoiceDateTo",
    )
    params: dict[str, Any] = {
        "invoiceDateFrom": date_from,
        "invoiceDateTo": date_to,
        "customerId": customer_id,
        "count": 50,
        "fields": "id,invoiceNumber,amount,amountCurrency,amountExcludingVat,amountExcludingVatCurrency,invoiceDate,invoiceComment,invoiceRemarks,orderLines(description)",
    }
    if invoice_number not in {None, ""}:
        params["invoiceNumber"] = invoice_number
    return params


def _invoice_search_params(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    invoice_number = lookup_analysis_value(task_analysis, "invoiceNumber", "invoice_number")
    customer_id = lookup_analysis_value(task_analysis, "customerId", "customer_id")
    if invoice_number in {None, ""} and customer_id in {None, ""}:
        return None

    date_from, date_to = best_effort_date_window(
        task_analysis,
        start_key="invoiceDateFrom",
        end_key="invoiceDateTo",
    )
    params: dict[str, Any] = {
        "invoiceDateFrom": date_from,
        "invoiceDateTo": date_to,
        "count": 10,
    }
    if invoice_number not in {None, ""}:
        params["invoiceNumber"] = invoice_number
    if customer_id not in {None, ""}:
        params["customerId"] = customer_id
    return params


def _invoice_payment_customer_ref(internal_task: InternalTask) -> dict[str, Any]:
    return _drop_empty(
        {
            "id": internal_task.search.get("customerId"),
            "organizationNumber": internal_task.search.get("customerOrganizationNumber"),
            "customerName": internal_task.search.get("customerName"),
        }
    )


def _invoice_payment_customer_search_params(internal_task: InternalTask) -> dict[str, Any]:
    return _drop_empty(
        {
            "organizationNumber": internal_task.search.get("customerOrganizationNumber"),
            "customerName": internal_task.search.get("customerName"),
            "count": 10,
        }
    )


def _invoice_payment_invoice_search_params(
    *,
    internal_task: InternalTask,
    task_analysis: TaskAnalysis,
    customer_id: Any | None,
) -> dict[str, Any] | None:
    invoice_number = internal_task.search.get("invoiceNumber")
    if invoice_number in {None, ""} and customer_id in {None, ""}:
        return None
    date_from = internal_task.search.get("invoiceDateFrom")
    date_to = internal_task.search.get("invoiceDateTo")
    if date_from in {None, ""} or date_to in {None, ""}:
        date_from, date_to = best_effort_date_window(
            task_analysis,
            start_key="invoiceDateFrom",
            end_key="invoiceDateTo",
        )
    params: dict[str, Any] = {
        "invoiceDateFrom": date_from,
        "invoiceDateTo": date_to,
        "count": 50,
        "fields": "id,invoiceNumber,amount,amountCurrency,amountExcludingVat,amountExcludingVatCurrency,invoiceDate,invoiceComment,invoiceRemarks,orderLines(description)",
    }
    if invoice_number not in {None, ""}:
        params["invoiceNumber"] = invoice_number
    if customer_id not in {None, ""}:
        params["customerId"] = customer_id
    return params


def _resolved_invoice_payment_target_invoice(
    history: list[dict[str, Any]],
    *,
    internal_task: InternalTask,
    task_analysis: TaskAnalysis,
    customer_id: Any | None,
) -> dict[str, Any] | None:
    target_invoice_number = internal_task.search.get("invoiceNumber")
    target_invoice_number = str(target_invoice_number) if target_invoice_number not in {None, ""} else None
    target_amount = _safe_float(internal_task.search.get("invoiceAmount") or internal_task.payload.get("paidAmount"))
    invoice = resolved_invoice_from_history(history, task_analysis)
    if invoice is not None and (
        target_invoice_number is None or str(invoice.get("invoiceNumber") or "") == target_invoice_number
    ):
        if target_amount is None or _invoice_candidate_matches_amount(invoice, target_amount):
            return invoice

    expected_search = _invoice_payment_invoice_search_params(
        internal_task=internal_task,
        task_analysis=task_analysis,
        customer_id=customer_id,
    )
    if expected_search is None:
        return None

    matches: list[dict[str, Any]] = []
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/invoice":
            continue
        if not _request_contains_params(request, expected_search):
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        if target_invoice_number is not None:
            for candidate in values:
                if str(candidate.get("invoiceNumber") or "") == target_invoice_number:
                    return candidate
        for candidate in values:
            if target_amount is not None and not _invoice_candidate_matches_amount(candidate, target_amount):
                continue
            matches.append(candidate)
        if target_amount is None and len(values) == 1:
            return values[0]

    if len(matches) == 1:
        return matches[0]
    return None


def _expense_increase_posting_search_params(period: dict[str, Any]) -> dict[str, Any] | None:
    date_from = period.get("dateFrom")
    date_to = period.get("dateTo")
    if date_from in {None, ""} or date_to in {None, ""}:
        return None
    return {
        "dateFrom": date_from,
        "dateTo": date_to,
        "count": 1000,
        "fields": "amount,account(id,number,name)",
    }


def _resolved_top_expense_increase_accounts(
    history: list[dict[str, Any]],
    *,
    internal_task: InternalTask,
    top_count: int,
) -> list[dict[str, Any]]:
    baseline_period = dict(internal_task.payload.get("baselinePeriod") or {})
    comparison_period = dict(internal_task.payload.get("comparisonPeriod") or {})
    baseline_params = _expense_increase_posting_search_params(baseline_period)
    comparison_params = _expense_increase_posting_search_params(comparison_period)
    if baseline_params is None or comparison_params is None:
        return []

    baseline_totals = _expense_account_totals(
        _posting_values_for_search(history, expected_params=baseline_params),
    )
    comparison_totals = _expense_account_totals(
        _posting_values_for_search(history, expected_params=comparison_params),
    )

    increases: list[dict[str, Any]] = []
    for account_key, comparison_value in comparison_totals.items():
        baseline_total = baseline_totals.get(account_key, {}).get("total", 0.0)
        increase = round(comparison_value["total"] - baseline_total, 2)
        if increase <= 0:
            continue
        increases.append(
            {
                "key": account_key,
                "id": comparison_value.get("id"),
                "number": comparison_value.get("number"),
                "name": comparison_value.get("name"),
                "increase": increase,
            }
        )

    increases.sort(key=lambda item: (-float(item["increase"]), str(item.get("name") or "")))
    return increases[: max(top_count, 1)]


def _posting_values_for_search(history: list[dict[str, Any]], *, expected_params: dict[str, Any]) -> list[dict[str, Any]]:
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/ledger/posting":
            continue
        if not _request_contains_params(request, expected_params):
            continue
        values = response.get("values") or []
        if isinstance(values, list):
            return [candidate for candidate in values if isinstance(candidate, dict)]
    return []


def _expense_account_totals(values: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for candidate in values:
        account = candidate.get("account")
        if not isinstance(account, dict):
            continue
        number_value = account.get("number")
        if not _is_expense_account_number(number_value):
            continue
        account_key = str(number_value)
        amount = _safe_float(candidate.get("amount"))
        if amount is None:
            continue
        entry = totals.setdefault(
            account_key,
            {
                "id": account.get("id"),
                "number": number_value,
                "name": account.get("name") or account_key,
                "total": 0.0,
            },
        )
        entry["total"] = round(float(entry["total"]) + amount, 2)
    return totals


def _is_expense_account_number(value: Any) -> bool:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return False
    return 4000 <= number < 9000


def _resolved_credit_note_target_invoice(
    history: list[dict[str, Any]],
    *,
    internal_task: InternalTask,
) -> dict[str, Any] | None:
    target_invoice_number = internal_task.payload.get("invoiceNumber")
    target_invoice_number = str(target_invoice_number) if target_invoice_number not in {None, ""} else None
    target_description = _normalized_text_match(internal_task.payload.get("description"))
    target_amount = _safe_float(internal_task.payload.get("amountExcludingVat"))

    matches: list[dict[str, Any]] = []
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        candidates: list[dict[str, Any]] = []
        if method == "GET" and path == "/invoice" and isinstance(response.get("values"), list):
            candidates = [candidate for candidate in response["values"] if isinstance(candidate, dict)]
        elif method == "GET" and path.startswith("/invoice/") and isinstance(response.get("value"), dict):
            candidates = [response["value"]]
        if not candidates:
            continue

        if target_invoice_number:
            for candidate in candidates:
                if str(candidate.get("invoiceNumber") or "") == target_invoice_number:
                    return candidate

        if target_description is None and target_amount is None and len(candidates) == 1:
            return candidates[0]

        for candidate in candidates:
            if target_description is not None and not _invoice_candidate_matches_description(candidate, target_description):
                continue
            if target_amount is not None and not _invoice_candidate_matches_amount(candidate, target_amount):
                continue
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0]
    return None


def _customer_search_params(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    organization_number = lookup_analysis_value(
        task_analysis,
        "organizationNumber",
        "customer_organizationNumber",
        "customerOrganizationNumber",
    )
    customer_name = lookup_analysis_value(
        task_analysis,
        "customerName",
        "customer_name",
        "name",
    )

    params: dict[str, Any] = {"count": 10, "fields": "id,name,organizationNumber"}
    if organization_number not in {None, ""}:
        params["organizationNumber"] = organization_number
        return params
    if customer_name not in {None, ""}:
        params["customerName"] = customer_name
        return params
    return None


def _build_customer_create_payload(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    organization_number = lookup_analysis_value(
        task_analysis,
        "organizationNumber",
        "customer_organizationNumber",
        "customerOrganizationNumber",
    )
    customer_name = lookup_analysis_value(
        task_analysis,
        "customerName",
        "customer_name",
        "name",
    )
    if customer_name in {None, ""}:
        return None
    payload: dict[str, Any] = {
        "name": customer_name,
        "isCustomer": True,
    }
    if organization_number not in {None, ""}:
        payload["organizationNumber"] = organization_number
    return payload


def _extract_order_line_specs(task_analysis: TaskAnalysis) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for key, value in task_analysis.payload_fields.items():
        match = re.fullmatch(r"orderLine(\d+)_(.+)", str(key))
        if not match:
            continue
        line_number = int(match.group(1))
        grouped.setdefault(line_number, {"line_number": line_number})[match.group(2)] = value

    specs: list[dict[str, Any]] = []
    for line_number in sorted(grouped):
        entry = grouped[line_number]
        product_number = entry.get("productNumber")
        description = entry.get("description")
        unit_price = entry.get("unitPrice")
        if product_number in {None, ""}:
            continue
        specs.append(
            {
                "line_number": line_number,
                "product_number": str(product_number),
                "description": str(description or ""),
                "unit_price": float(unit_price) if unit_price not in {None, ""} else None,
                "count": float(entry.get("count") or 1),
            }
        )
    return specs


def _build_product_create_payload(spec: dict[str, Any]) -> dict[str, Any] | None:
    if not spec.get("description"):
        return None
    payload: dict[str, Any] = {
        "name": spec["description"],
        "number": spec["product_number"],
    }
    if spec.get("unit_price") not in {None, ""}:
        payload["priceExcludingVatCurrency"] = spec["unit_price"]
    return payload


def _build_order_create_payload(
    task_analysis: TaskAnalysis,
    *,
    customer: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    customer_id = customer.get("id")
    if customer_id in {None, ""}:
        return None

    line_specs = _extract_order_line_specs(task_analysis)
    order_lines: list[dict[str, Any]] = []
    for spec in line_specs:
        product = _resolved_product_from_history(history, task_analysis, line_number=spec["line_number"])
        if product is None or product.get("id") in {None, ""}:
            return None
        line: dict[str, Any] = {
            "product": {"id": product["id"]},
            "description": spec["description"] or product.get("name"),
            "count": spec["count"],
        }
        if spec.get("unit_price") not in {None, ""}:
            line["unitPriceExcludingVatCurrency"] = spec["unit_price"]
        order_lines.append(line)

    if not order_lines:
        return None

    return {
        "customer": {"id": customer_id},
        "orderDate": default_action_date(task_analysis, "orderDate", "date"),
        "orderLines": order_lines,
    }


def _resolved_customer_from_history(history: list[dict[str, Any]], task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    target_org = lookup_analysis_value(
        task_analysis,
        "organizationNumber",
        "customer_organizationNumber",
        "customerOrganizationNumber",
    )
    target_name = lookup_analysis_value(task_analysis, "customerName", "customer_name", "name")
    target_org = str(target_org) if target_org not in {None, ""} else None
    target_name = str(target_name).lower() if target_name not in {None, ""} else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if path == "/customer" and method == "POST" and isinstance(response.get("value"), dict):
            return response["value"]
        if path == "/customer" and method == "GET":
            values = response.get("values") or []
            if not isinstance(values, list):
                continue
            for candidate in values:
                if not isinstance(candidate, dict):
                    continue
                if target_org and str(candidate.get("organizationNumber")) == target_org:
                    return candidate
                if target_name and str(candidate.get("name") or "").lower() == target_name:
                    return candidate
            if len(values) == 1 and isinstance(values[0], dict):
                return values[0]
    return None


def _resolved_product_from_history(
    history: list[dict[str, Any]],
    task_analysis: TaskAnalysis,
    *,
    line_number: int,
) -> dict[str, Any] | None:
    specs = {spec["line_number"]: spec for spec in _extract_order_line_specs(task_analysis)}
    spec = specs.get(line_number)
    if spec is None:
        return None
    target_number = spec["product_number"]

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if path == "/product" and method == "POST" and isinstance(response.get("value"), dict):
            candidate = response["value"]
            if str(candidate.get("number")) == target_number:
                return candidate
        if path == "/product" and method == "GET":
            values = response.get("values") or []
            if not isinstance(values, list):
                continue
            for candidate in values:
                if isinstance(candidate, dict) and str(candidate.get("number")) == target_number:
                    return candidate
    return None


def _resolved_order_from_history(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("path") or "") != "/order" or str(request.get("method") or "").upper() != "POST":
            continue
        if isinstance(response.get("value"), dict):
            return response["value"]
    return None


def _order_total_amount(task_analysis: TaskAnalysis) -> float | None:
    total = 0.0
    line_specs = _extract_order_line_specs(task_analysis)
    if not line_specs:
        return None
    for spec in line_specs:
        unit_price = spec.get("unit_price")
        if unit_price in {None, ""}:
            return None
        total += float(unit_price) * float(spec.get("count") or 1)
    return total


def _fallback_first_payment_type_id(history: list[dict[str, Any]]) -> Any | None:
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("path") or "") != "/invoice/paymentType":
            continue
        for candidate in response.get("values") or []:
            if isinstance(candidate, dict) and candidate.get("id") not in {None, ""}:
                return candidate["id"]
    return None


def _resolved_supplier_invoice_voucher_type_id(
    history: list[dict[str, Any]],
    *,
    voucher_type_name: Any | None,
) -> Any | None:
    target_name = _normalized_text_match(voucher_type_name)
    fallback_id = None
    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != "GET" or str(request.get("path") or "") != "/ledger/voucherType":
            continue
        values = [candidate for candidate in (response.get("values") or []) if isinstance(candidate, dict)]
        for candidate in values:
            candidate_id = candidate.get("id")
            if candidate_id in {None, ""}:
                continue
            candidate_name = _normalized_text_match(candidate.get("name") or candidate.get("displayName"))
            if target_name and candidate_name and target_name in candidate_name:
                return candidate_id
            if candidate_name and any(token in candidate_name for token in ("supplier", "leverand")):
                fallback_id = candidate_id
        if fallback_id is None and len(values) == 1 and values[0].get("id") not in {None, ""}:
            fallback_id = values[0]["id"]
    return fallback_id


def _normalized_text_match(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    normalized = " ".join(str(value).strip().casefold().split())
    return normalized or None


def _invoice_candidate_matches_description(candidate: dict[str, Any], target_description: str) -> bool:
    haystacks: list[str] = []
    for key in ("invoiceComment", "invoiceRemarks", "description"):
        normalized = _normalized_text_match(candidate.get(key))
        if normalized:
            haystacks.append(normalized)
    for line in candidate.get("orderLines") or []:
        if not isinstance(line, dict):
            continue
        normalized = _normalized_text_match(line.get("description"))
        if normalized:
            haystacks.append(normalized)
    return any(target_description in haystack or haystack in target_description for haystack in haystacks)


def _invoice_candidate_matches_amount(candidate: dict[str, Any], target_amount: float) -> bool:
    for key in ("amountExcludingVat", "amountExcludingVatCurrency", "amount", "amountCurrency"):
        candidate_amount = _safe_float(candidate.get(key))
        if candidate_amount is None:
            continue
        if round(candidate_amount, 2) == round(target_amount, 2):
            return True
    return False


def _safe_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_order_invoice_workflow(task_analysis: TaskAnalysis, *, combined_text: str) -> bool:
    family = task_analysis.task_family.lower()
    if "order" not in family and (task_analysis.target_resource or "").lower() != "order":
        return False
    return any(token in combined_text for token in ("invoice", "payment", "paid", "full payment", "register full payment"))


def _looks_like_create(task_analysis: TaskAnalysis) -> bool:
    return task_analysis.operation == "create" or task_analysis.task_family.lower().endswith(".create")


def _build_employee_create_payload(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    first_name = lookup_analysis_value(task_analysis, "firstName", "first_name")
    last_name = lookup_analysis_value(task_analysis, "lastName", "last_name")

    if first_name in {None, ""} or last_name in {None, ""}:
        full_name = lookup_analysis_value(task_analysis, "name", "fullName", "displayName")
        if full_name not in {None, ""}:
            parts = str(full_name).strip().split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])

    if first_name in {None, ""} or last_name in {None, ""}:
        return None

    payload: dict[str, Any] = {
        "firstName": first_name,
        "lastName": last_name,
    }
    for source_key, target_key in (
        ("email", "email"),
        ("employeeNumber", "employeeNumber"),
        ("phoneNumberMobile", "phoneNumberMobile"),
        ("phoneNumber", "phoneNumberWork"),
    ):
        value = lookup_analysis_value(task_analysis, source_key)
        if value not in {None, ""}:
            payload[target_key] = value
    return payload


def _employee_search_params(task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    email = lookup_analysis_value(task_analysis, "email")
    if email not in {None, ""}:
        return {
            "email": email,
            "count": 10,
        }

    first_name = lookup_analysis_value(task_analysis, "firstName", "first_name")
    last_name = lookup_analysis_value(task_analysis, "lastName", "last_name")
    if first_name not in {None, ""} or last_name not in {None, ""}:
        params = {"count": 10}
        if first_name not in {None, ""}:
            params["firstName"] = first_name
        if last_name not in {None, ""}:
            params["lastName"] = last_name
        return params
    return None


def _resolved_employee_from_history(history: list[dict[str, Any]], task_analysis: TaskAnalysis) -> dict[str, Any] | None:
    target_email = lookup_analysis_value(task_analysis, "email")
    target_email = str(target_email).lower() if target_email not in {None, ""} else None

    for entry in reversed(history):
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        request = entry.get("request") or {}
        path = str(request.get("path") or "")
        method = str(request.get("method") or "").upper()
        if path == "/employee" and method in {"POST"} and isinstance(response.get("value"), dict):
            return response["value"]
        if path.startswith("/employee/") and method == "GET" and isinstance(response.get("value"), dict):
            return response["value"]
        if path == "/employee" and method == "GET":
            values = response.get("values") or []
            if not isinstance(values, list):
                continue
            if target_email:
                for candidate in values:
                    if isinstance(candidate, dict) and str(candidate.get("email") or "").lower() == target_email:
                        return candidate
            if len(values) == 1 and isinstance(values[0], dict):
                return values[0]
    return None


def _has_success(
    history: list[dict[str, Any]],
    *,
    method: str,
    path_prefix: str | None = None,
    path_suffix: str | None = None,
) -> bool:
    for entry in reversed(history):
        if "response" not in entry:
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        path = str(request.get("path") or "")
        if path_prefix is not None and not path.startswith(path_prefix):
            continue
        if path_suffix is not None and not path.endswith(path_suffix):
            continue
        return True
    return False


def _has_attempt_exact(history: list[dict[str, Any]], *, method: str, path: str) -> bool:
    return _has_attempt_exact_where(history, method=method, path=path, predicate=None)


def _has_attempt_exact_where(
    history: list[dict[str, Any]],
    *,
    method: str,
    path: str,
    predicate: Any | None,
) -> bool:
    for entry in reversed(history):
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        if str(request.get("path") or "") != path:
            continue
        if predicate is not None and not predicate(request):
            continue
        return True
    return False


def _has_success_exact(history: list[dict[str, Any]], *, method: str, path: str) -> bool:
    return _has_success_exact_where(history, method=method, path=path, predicate=None)


def _has_success_exact_where(
    history: list[dict[str, Any]],
    *,
    method: str,
    path: str,
    predicate: Any | None,
) -> bool:
    for entry in reversed(history):
        if "response" not in entry:
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        if str(request.get("path") or "") != path:
            continue
        if predicate is not None and not predicate(request):
            continue
        return True
    return False


def _has_api_error_exact_where(
    history: list[dict[str, Any]],
    *,
    method: str,
    path: str,
    predicate: Any | None,
) -> bool:
    for entry in reversed(history):
        error = entry.get("error")
        if not isinstance(error, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        if str(request.get("path") or "") != path:
            continue
        if error.get("type") != "tripletex_api":
            continue
        if predicate is not None and not predicate(request):
            continue
        return True
    return False


def _latest_api_error_exact_where(
    history: list[dict[str, Any]],
    *,
    method: str,
    path: str,
    predicate: Any | None,
) -> dict[str, Any] | None:
    for entry in reversed(history):
        error = entry.get("error")
        if not isinstance(error, dict):
            continue
        request = entry.get("request") or {}
        if str(request.get("method") or "").upper() != method.upper():
            continue
        if str(request.get("path") or "") != path:
            continue
        if error.get("type") != "tripletex_api":
            continue
        if predicate is not None and not predicate(request):
            continue
        return error
    return None


def _tripletex_error_summary(error: dict[str, Any]) -> str:
    status_code = error.get("status_code")
    message = str(error.get("message") or "").strip()
    if message:
        if status_code in {None, ""}:
            return message
        return f"{status_code} {message}"
    if status_code not in {None, ""}:
        return f"{status_code}"
    return "unknown Tripletex API error"


def _incoming_invoice_external_id(
    *,
    supplier_id: Any,
    invoice_number: Any,
    invoice_date: Any,
    description: Any,
) -> str:
    raw_value = invoice_number or f"{supplier_id}-{invoice_date or description or 'supplier-invoice'}"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw_value)).strip("-")
    if not normalized:
        normalized = f"supplier-invoice-{supplier_id}"
    return normalized[:120]


def _finish_reason_indicates_failure(reason: str) -> bool:
    normalized = " ".join(str(reason).strip().lower().split())
    return any(
        token in normalized
        for token in (
            "unable to",
            "cannot ",
            "can't ",
            "could not",
            "did not",
            "not found",
            "no results",
            "no matching",
            "failed to",
            "cannot proceed",
            "couldn't",
        )
    )


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


def _decision_signature(decision: PlannerDecision | None) -> Any:
    if decision is None:
        return {"kind": "none"}
    if decision.kind == "action" and decision.action is not None:
        return {
            "kind": "action",
            "method": decision.action.method,
            "path": decision.action.path,
            "params": _trim_payload(decision.action.params, max_depth=2, max_items=4),
            "json": _trim_payload(decision.action.json_body, max_depth=2, max_items=4),
            "reason": decision.reason[:160],
        }
    if decision.kind == "method" and decision.method_call is not None:
        return {
            "kind": "method",
            "method_name": decision.method_call.method_name,
            "arguments": _trim_payload(decision.method_call.arguments, max_depth=2, max_items=4),
            "reason": decision.reason[:160],
        }
    return {"kind": decision.kind, "reason": decision.reason[:160]}
