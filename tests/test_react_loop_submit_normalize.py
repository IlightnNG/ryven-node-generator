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


if __name__ == "__main__":
    unittest.main()

