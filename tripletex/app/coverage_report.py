from __future__ import annotations

from typing import Any

from .internal_tasks import (
    METHOD_SPECS,
    _openapi_workflow_method_name,
    documented_task_category_coverage,
    documented_task_category_gaps,
    method_coverage_snapshot,
)
from .openapi_registry import TripletexOpenAPIRegistry, workflow_resource_families
from .tasking import TASK_ANALYSIS_CONTRACT_VERSION


def build_coverage_report() -> dict[str, Any]:
    registry = TripletexOpenAPIRegistry.from_default_spec()
    category_coverage = documented_task_category_coverage()
    methods = method_coverage_snapshot()
    coded_methods = sum(1 for item in methods if item["coverage_status"] == "coded")
    wrapper_only_methods = sum(1 for item in methods if item["coverage_status"] == "wrapper_only")
    unsupported_methods = sum(1 for item in methods if item["coverage_status"] == "unsupported")
    resource_support_matrix: list[dict[str, Any]] = []
    for resource_family, _label in workflow_resource_families():
        capability = registry.resource_capability(resource_family)
        wrapper_method_name = _openapi_workflow_method_name(resource_family)
        wrapper_spec = METHOD_SPECS.get(wrapper_method_name)
        curated_methods = sorted(
            spec.name
            for spec in METHOD_SPECS.values()
            if spec.coverage_status == "coded" and spec.target_resource == resource_family
        )
        resource_support_matrix.append(
            {
                "resource_family": resource_family,
                "planner_method": wrapper_method_name,
                "wrapper_coverage_status": wrapper_spec.coverage_status if wrapper_spec is not None else "unsupported",
                "curated_methods": curated_methods,
                "deterministic_execution_supported": bool(capability.supported_methods),
                "verification_support": capability.supports_search or capability.detail_path is not None,
                "destructive_support": capability.supports_delete or capability.supports_reverse,
            }
        )
    return {
        "contract_version": TASK_ANALYSIS_CONTRACT_VERSION,
        "method_count": len(METHOD_SPECS),
        "coded_method_count": coded_methods,
        "wrapper_only_method_count": wrapper_only_methods,
        "unsupported_method_count": unsupported_methods,
        "documented_task_category_coverage": category_coverage,
        "documented_task_category_gaps": documented_task_category_gaps(),
        "methods": methods,
        "resource_capabilities": registry.capability_report(),
        "resource_support_matrix": resource_support_matrix,
    }
