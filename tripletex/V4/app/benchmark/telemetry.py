from __future__ import annotations

from typing import Any

from app.benchmark.models import BenchmarkAnalysis


def analysis_log_payload(analysis: BenchmarkAnalysis) -> dict[str, Any]:
    return {
        "selectedFamily": analysis.selected_family_id,
        "selectedRouteKind": analysis.selected_route_kind,
        "selectedRouteName": analysis.selected_route_name,
        "selectedFlow": analysis.selected_flow_name,
        "selectedExecutor": analysis.selected_executor_name,
        "executionMode": analysis.execution_mode,
        "supportedByExecutor": analysis.supported_by_executor,
        "attachments": len(analysis.normalized_request.attachments),
        "candidates": [
            {
                "family": candidate.family_id,
                "score": candidate.score,
                "confidence": candidate.confidence,
            }
            for candidate in analysis.candidates
        ],
        "notes": list(analysis.notes),
    }
