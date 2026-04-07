"""context_budget: history trim + compact node JSON."""

from __future__ import annotations

import json
import unittest

from langchain_core.messages import HumanMessage, SystemMessage

from ryven_node_generator.ai_assistant.context_budget import (
    build_node_context_json,
    trim_history_pairs,
    truncate_history_message_texts,
)
from ryven_node_generator.ai_assistant.orchestration.react_loop import _apply_compress_prior_turns
from ryven_node_generator.ai_assistant.tools.host import ReactToolHost


class TestTrimHistoryPairs(unittest.TestCase):
    def test_unlimited_when_max_zero(self):
        h = [("user", "a"), ("assistant", "b"), ("user", "c")]
        self.assertEqual(trim_history_pairs(h, max_user_assistant_messages=0), h)

    def test_drops_system_and_keeps_tail(self):
        h = [("user", str(i)) for i in range(10)]
        h.insert(2, ("system", "noise"))
        out = trim_history_pairs(h, max_user_assistant_messages=4)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0][1], "6")
        self.assertEqual(out[-1][1], "9")

    def test_compact_json_no_whitespace_block(self):
        s = build_node_context_json(
            {"class_name": "N", "core_logic": "pass"},
            ["A", "B"],
            compact=True,
        )
        self.assertNotIn("\n", s)
        data = json.loads(s)
        self.assertEqual(data["existing_class_names"], ["A", "B"])

    def test_truncate_history_message_texts(self):
        long = "x" * 500
        out = truncate_history_message_texts(
            [("user", long), ("assistant", "ok")],
            max_chars_per_message=120,
        )
        self.assertIn("truncated", out[0][1])
        self.assertLessEqual(len(out[0][1]), 120)
        self.assertEqual(out[1][1], "ok")

    def test_truncate_unlimited_when_zero(self):
        long = "y" * 5000
        out = truncate_history_message_texts([("assistant", long)], max_chars_per_message=0)
        self.assertEqual(out[0][1], long)

    def test_apply_compress_prior_turns_keep_zero(self):
        messages = [
            SystemMessage(content="s0"),
            SystemMessage(content="s1"),
            HumanMessage(content="old"),
            HumanMessage(content="current user"),
        ]
        ref = [3]
        msg = _apply_compress_prior_turns(
            messages,
            history_start_idx=2,
            current_user_msg_idx_ref=ref,
            summary_of_older_turns="SUMMARY",
            keep_last_messages=0,
        )
        self.assertIn("[ok]", msg)
        self.assertEqual(ref[0], 3)
        self.assertIn("SUMMARY", messages[2].content)
        self.assertEqual(messages[3].content, "current user")

    def test_validate_core_logic_uses_draft_when_empty(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            h = ReactToolHost(
                project_root=Path(d),
                draft_ref={"node": {"core_logic": "pass"}},
                existing_class_names=[],
            )
            out = json.loads(h.validate_core_logic_tool(""))
            self.assertTrue(out.get("ok"))


if __name__ == "__main__":
    unittest.main()
