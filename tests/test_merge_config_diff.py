"""whitelisted_config_diff and ReAct submit finalization (no LLM)."""

from __future__ import annotations

import copy
import unittest

from ryven_node_generator.ai_assistant.merge import whitelisted_config_diff
from ryven_node_generator.ai_assistant.orchestration.react_loop import _finalize_submit_turn
from ryven_node_generator.ai_assistant.schemas import AssistantTurn


class TestWhitelistedConfigDiff(unittest.TestCase):
    def test_diff_omits_unchanged_and_core_logic_key(self):
        base = {
            "class_name": "N",
            "title": "T",
            "inputs": [],
            "outputs": [],
            "core_logic": "pass",
        }
        eff = {
            "class_name": "N",
            "title": "T2",
            "inputs": [{"label": "a"}],
            "outputs": [],
            "core_logic": "x=1",
        }
        d = whitelisted_config_diff(base, eff)
        self.assertEqual(d.get("title"), "T2")
        self.assertEqual(len(d.get("inputs") or []), 1)
        self.assertNotIn("core_logic", d)
        self.assertNotIn("class_name", d)
        self.assertNotIn("outputs", d)

    def test_deepcopy_is_independent(self):
        base = {"inputs": []}
        eff = {"inputs": [{"label": "x"}]}
        d = whitelisted_config_diff(base, eff)
        d["inputs"][0]["label"] = "y"
        self.assertEqual(eff["inputs"][0]["label"], "x")


class TestFinalizeSubmitTurn(unittest.TestCase):
    def test_submit_only_core_logic_still_carries_port_diff_from_draft(self):
        baseline = {
            "class_name": "A",
            "title": "Old",
            "description": "",
            "color": "#fff",
            "inputs": [],
            "outputs": [],
            "core_logic": "pass",
        }
        draft = copy.deepcopy(baseline)
        draft["title"] = "New"
        draft["inputs"] = [{"label": "in0", "type": "data"}]
        draft["core_logic"] = "y=2"
        turn = AssistantTurn(message="ok", core_logic="x = 1", config_patch=None)
        out = _finalize_submit_turn(turn, draft, baseline)
        self.assertEqual(out.core_logic.strip(), "x = 1")
        self.assertIsNotNone(out.config_patch)
        self.assertEqual(out.config_patch.get("title"), "New")
        self.assertEqual(len(out.config_patch.get("inputs") or []), 1)

    def test_submit_config_patch_overlays_draft(self):
        baseline = {
            "class_name": "A",
            "title": "Old",
            "description": "",
            "color": "#fff",
            "inputs": [],
            "outputs": [],
            "core_logic": "pass",
        }
        draft = copy.deepcopy(baseline)
        turn = AssistantTurn(
            message="ok",
            core_logic=None,
            config_patch={"title": "FromSubmit"},
        )
        out = _finalize_submit_turn(turn, draft, baseline)
        self.assertEqual(out.config_patch.get("title"), "FromSubmit")


if __name__ == "__main__":
    unittest.main()
