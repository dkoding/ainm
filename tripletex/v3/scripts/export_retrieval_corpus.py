#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.llm.retrieval_docs import (
    render_command_retrieval_doc,
    render_flow_retrieval_doc,
    render_raw_operation_retrieval_doc,
    retrieval_document_filename,
)
from app.raw import load_raw_catalog
from app.wrapper import load_wrapper_catalog


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export operation-, command-, and flow-level retrieval documents for Vertex RAG ingestion."
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/retrieval_corpus",
        help="Directory where retrieval documents will be written.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    raw_catalog = load_raw_catalog()
    wrapper_catalog = load_wrapper_catalog()

    documents = {
        "flows": 0,
        "commands": 0,
        "raw_operations": 0,
    }

    for subdir in ("flows", "commands", "raw_operations"):
        (output_dir / subdir).mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []

    for flow in wrapper_catalog.list_flows():
        filename = retrieval_document_filename("flow", flow["flowName"])
        path = output_dir / "flows" / filename
        path.write_text(render_flow_retrieval_doc(flow) + "\n", encoding="utf-8")
        manifest.append({"docType": "flow", "name": flow["flowName"], "path": str(path.relative_to(output_dir))})
        documents["flows"] += 1

    for command in wrapper_catalog.list_commands():
        raw_meta = raw_catalog.get(command["operationId"])
        filename = retrieval_document_filename("command", command["commandName"])
        path = output_dir / "commands" / filename
        path.write_text(render_command_retrieval_doc(command, raw_meta) + "\n", encoding="utf-8")
        manifest.append({"docType": "command", "name": command["commandName"], "path": str(path.relative_to(output_dir))})
        documents["commands"] += 1

    for operation_id, operation in sorted(raw_catalog.operations.items()):
        filename = retrieval_document_filename("raw_operation", operation_id)
        path = output_dir / "raw_operations" / filename
        path.write_text(render_raw_operation_retrieval_doc(operation) + "\n", encoding="utf-8")
        manifest.append({"docType": "raw_operation", "name": operation_id, "path": str(path.relative_to(output_dir))})
        documents["raw_operations"] += 1

    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "counts": documents,
                "documents": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"outputDir": str(output_dir), "counts": documents}, ensure_ascii=False))


if __name__ == "__main__":
    main()
