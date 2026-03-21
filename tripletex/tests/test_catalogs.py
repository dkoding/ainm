from __future__ import annotations

import unittest

from app.raw import load_raw_catalog
from app.wrapper import load_wrapper_catalog


class CatalogCoverageTests(unittest.TestCase):
    def test_generated_counts_match_docs(self) -> None:
        raw_catalog = load_raw_catalog()
        wrapper_catalog = load_wrapper_catalog()
        self.assertEqual(raw_catalog.count, 800)
        self.assertEqual(wrapper_catalog.command_count, 78)
        self.assertEqual(wrapper_catalog.flow_count, 21)

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


if __name__ == "__main__":
    unittest.main()
