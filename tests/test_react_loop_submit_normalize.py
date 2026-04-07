"""Unit tests for submit_node_turn args normalization."""

from __future__ import annotations

import unittest

from ryven_node_generator.ai_assistant.orchestration.react_loop import _normalize_submit_turn_args
from ryven_node_generator.ai_assistant.schemas import AssistantTurn


class TestReactLoopSubmitNormalize(unittest.TestCase):
    def test_config_patch_string_json_is_parsed(self):
        raw_args = {
            "message": "ok",
            "core_logic": "x = 1",
            # Model mistake: config_patch passed as a JSON-encoded string.
            "config_patch": '{"title":"T","inputs":[],"outputs":[],"class_name":"N"}',
        }
        norm = _normalize_submit_turn_args(raw_args)
        self.assertIsInstance(norm["config_patch"], dict)
        turn = AssistantTurn.model_validate(norm)
        self.assertEqual(turn.config_patch.get("title"), "T")

    def test_empty_string_config_patch_and_core_logic_coerced(self):
        raw_args = {
            "message": "Shell done.",
            "core_logic": "",
            "config_patch": "",
        }
        norm = _normalize_submit_turn_args(raw_args)
        self.assertIsNone(norm.get("core_logic"))
        self.assertIsNone(norm.get("config_patch"))
        turn = AssistantTurn.model_validate(norm)
        self.assertIsNone(turn.config_patch)
        self.assertIsNone(turn.core_logic)

    def test_self_test_cases_empty_string_becomes_none(self):
        raw_args = {"message": "ok", "core_logic": "pass", "self_test_cases": ""}
        norm = _normalize_submit_turn_args(raw_args)
        self.assertIsNone(norm.get("self_test_cases"))
        AssistantTurn.model_validate(norm)


if __name__ == "__main__":
    unittest.main()

