from __future__ import annotations

import unittest

from app.benchmark import TaskRegistry


class TaskRegistryTests(unittest.TestCase):
    def test_registry_loads_thirty_task_families(self) -> None:
        registry = TaskRegistry()

        family_ids = registry.list_family_ids()

        self.assertEqual(len(family_ids), 30)
        self.assertEqual(len(set(family_ids)), 30)

    def test_attachment_manifest_requires_attachment(self) -> None:
        registry = TaskRegistry()

        manifest = registry.get("supplier_invoice.import_from_attachment")

        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertTrue(manifest.requires_attachment)
        self.assertEqual(manifest.preferred_flow_name, "supplier_invoice.import_from_attachment")


if __name__ == "__main__":
    unittest.main()
