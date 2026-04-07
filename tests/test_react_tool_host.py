"""ReactToolHost without LLM."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ryven_node_generator.ai_assistant.tools.host import ReactToolHost


class TestReactToolHost(unittest.TestCase):
    def test_apply_patch(self):
        draft = {"node": {"class_name": "A", "title": "t", "inputs": [], "outputs": [], "core_logic": "pass"}}
        host = ReactToolHost(
            project_root=Path("."),
            draft_ref=draft,
            existing_class_names=[],
        )
        msg = host.apply_node_patch(json.dumps({"title": "New"}))
        self.assertIn("ok", msg.lower())
        self.assertEqual(draft["node"]["title"], "New")

    def test_read_write_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            draft = {"node": {"class_name": "X"}}
            host = ReactToolHost(project_root=root, draft_ref=draft, existing_class_names=[])
            w = host.write_project_file("sub/hello.txt", "abc")
            self.assertIn("ok", w.lower())
            r = host.read_project_file("sub/hello.txt")
            self.assertEqual(r, "abc")


if __name__ == "__main__":
    unittest.main()
