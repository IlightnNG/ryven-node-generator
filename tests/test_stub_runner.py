"""Stub runner logic (no LLM)."""

from __future__ import annotations

import unittest

from ryven_node_generator.ai_assistant.core.stub_runner import evaluate_stub_cases, normalize_test_cases


class TestStubRunner(unittest.TestCase):
    def test_evaluate_simple(self):
        node = {
            "inputs": [{"label": "a", "type": "data"}],
            "outputs": [{"label": "o", "type": "data"}],
        }
        cases = normalize_test_cases(None, node)
        r = evaluate_stub_cases("self.set_output_val(0, Data(1))", node, cases)
        self.assertTrue(r["all_passed"])


if __name__ == "__main__":
    unittest.main()
