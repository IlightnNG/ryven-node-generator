"""Regression anchors for AssistantTurn JSON and merge semantics (no live LLM)."""

from __future__ import annotations

import unittest

from ryven_node_generator.ai_assistant.json_parse import parse_assistant_turn_json
from ryven_node_generator.ai_assistant.merge import apply_config_patch
from ryven_node_generator.ai_assistant.schemas import AssistantTurn
from ryven_node_generator.ai_assistant.core.finalize_turn import finalize_parsed_turn


class TestAssistantTurnContract(unittest.TestCase):
    def test_parse_and_finalize_keys(self):
        raw = (
            '{"message":"Hello.","core_logic":"x = 1","config_patch":{"title":"T"},'
            '"self_test_cases":[{"inputs":[1],"note":"n"}]}'
        )
        parsed = parse_assistant_turn_json(raw)
        self.assertIsInstance(parsed, AssistantTurn)
        self.assertEqual(parsed.message.strip(), "Hello.")
        out = finalize_parsed_turn(parsed)
        self.assertIn("message", out)
        self.assertIn("core_logic", out)
        self.assertIn("config_patch", out)
        self.assertIn("self_test_cases", out)
        self.assertIn("validation_error", out)
        # config_patch strips core_logic duplicate into top-level core_logic path
        self.assertIsInstance(out["self_test_cases"], list)

    def test_apply_config_patch_merge(self):
        node = {
            "class_name": "NodeA",
            "title": "Old",
            "description": "d",
            "color": "#fff",
            "inputs": [],
            "outputs": [],
            "core_logic": "pass",
        }
        patch = {"title": "New", "disallowed_key": 1}
        skipped = apply_config_patch(node, patch)
        self.assertEqual(node["title"], "New")
        self.assertTrue(any("disallowed" in s for s in skipped))

    def test_json_sep_constant(self):
        from ryven_node_generator.ai_assistant.contracts.streaming import JSON_SEP

        self.assertEqual(JSON_SEP, "<<<JSON>>>")


if __name__ == "__main__":
    unittest.main()
