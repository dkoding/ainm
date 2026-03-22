from __future__ import annotations

from pathlib import Path
import unittest

from app.openapi_catalog import load_openapi_catalog
from app.raw import load_raw_catalog
from app.wrapper import load_wrapper_catalog


class CatalogCoverageTests(unittest.TestCase):
    def test_generated_counts_match_docs(self) -> None:
        raw_catalog = load_raw_catalog()
        wrapper_catalog = load_wrapper_catalog()
        self.assertEqual(raw_catalog.count, 800)
        self.assertEqual(wrapper_catalog.command_count, 84)
        self.assertEqual(wrapper_catalog.flow_count, 23)

    def test_all_raw_operations_have_technical_family(self) -> None:
        raw_catalog = load_raw_catalog()
        missing = [
            operation_id
            for operation_id, meta in raw_catalog.operations.items()
            if not meta.get("technicalFlowFamily")
        ]
        self.assertEqual(missing, [])

    def test_all_wrapper_commands_map_to_known_raw_operations(self) -> None:
        raw_catalog = load_raw_catalog()
        wrapper_catalog = load_wrapper_catalog()
        missing = [
            name
            for name, meta in wrapper_catalog.commands.items()
            if not raw_catalog.has(meta["operationId"])
        ]
        self.assertEqual(missing, [])

    def test_wrapper_catalog_exposes_semantic_selector_and_payload_contracts(self) -> None:
        wrapper_catalog = load_wrapper_catalog()
        self.assertIn("employee_selector", wrapper_catalog.selector_families)
        self.assertIn("travel_details", wrapper_catalog.payload_families)
        travel_flow = wrapper_catalog.get_flow("travel_expense.create_with_rows")
        self.assertIn("cost_rows", travel_flow["inputs"])
        self.assertNotIn("cost_rows[]", travel_flow["inputs"])
        self.assertEqual(
            travel_flow["inputSemantics"]["travel_details"]["payloadFamily"],
            "travel_details",
        )

    def test_openapi_catalog_resolves_nested_order_line_fields_from_docs(self) -> None:
        schema = load_openapi_catalog().body_schema("Order_post")
        order_line_schema = schema["properties"]["orderLines"]["items"]
        self.assertIn("unitPriceExcludingVatCurrency", order_line_schema["properties"])
        self.assertIn("unitPriceIncludingVatCurrency", order_line_schema["properties"])

    def test_generated_operation_catalog_stays_compact_enough_for_cloud_run_startup(self) -> None:
        operation_catalog = Path(__file__).resolve().parents[1] / "app" / "generated" / "operation_catalog.json"
        self.assertLess(operation_catalog.stat().st_size, 25 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
