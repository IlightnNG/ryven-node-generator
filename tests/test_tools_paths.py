"""Tool path and shell guards."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from ryven_node_generator.ai_assistant.tools.safe_path import resolve_under_root
from ryven_node_generator.ai_assistant.tools.shell_guards import check_shell_command


class TestSafePath(unittest.TestCase):
    def test_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "a" / "b.txt"
            p.parent.mkdir(parents=True)
            p.write_text("x", encoding="utf-8")
            got = resolve_under_root(root, "a/b.txt")
            self.assertEqual(got, p.resolve())

    def test_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                resolve_under_root(root, "../outside")


class TestShellGuards(unittest.TestCase):
    def test_simple_ok(self):
        ok, _ = check_shell_command(f'"{sys.executable}" --version')
        self.assertTrue(ok)

    def test_chain_blocked(self):
        ok, _ = check_shell_command("echo a && echo b")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
