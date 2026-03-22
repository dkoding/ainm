from __future__ import annotations

import unittest

from app.llm.json_payloads import load_json_payload


class JsonPayloadsTests(unittest.TestCase):
    def test_load_json_payload_accepts_trailing_commas_and_smart_quotes(self) -> None:
        payload = '```json\n{“contractVersion”: “tripletex.llm_bridge.v1”, “validation”: {“isExecutable”: false,},}\n```'

        data = load_json_payload(payload)

        self.assertEqual(data["contractVersion"], "tripletex.llm_bridge.v1")
        self.assertFalse(data["validation"]["isExecutable"])

    def test_load_json_payload_accepts_single_quoted_json_like_object(self) -> None:
        payload = "{'contractVersion': 'tripletex.llm_bridge.v1', 'validation': {'isExecutable': true}}"

        data = load_json_payload(payload)

        self.assertEqual(data["contractVersion"], "tripletex.llm_bridge.v1")
        self.assertTrue(data["validation"]["isExecutable"])


if __name__ == "__main__":
    unittest.main()
