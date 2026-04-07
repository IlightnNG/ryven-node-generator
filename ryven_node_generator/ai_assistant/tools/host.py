"""Executable tool implementations (no LangChain). Used by ReAct tool wrappers."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

from ..config import (
    ai_agent_bash_enabled,
    ai_agent_max_read_file_chars,
    ai_agent_max_tool_output_chars,
    ai_agent_max_write_file_bytes,
    ai_agent_shell_timeout_sec,
)
from ..core.stub_runner import evaluate_stub_cases, normalize_test_cases
from ..merge import apply_config_patch
from ..validation import dedent_core_logic, validate_core_logic
from .safe_path import resolve_under_root
from .shell_guards import check_shell_command


class ReactToolHost:
    """Per-session host: project files + draft node mutations + stub run + optional shell."""

    def __init__(
        self,
        *,
        project_root: Path,
        draft_ref: dict[str, Any],
        existing_class_names: list[str],
    ) -> None:
        self.project_root = project_root.expanduser().resolve()
        self.draft_ref = draft_ref
        self.existing_class_names = existing_class_names

    def read_project_file(self, relative_path: str) -> str:
        """Read a UTF-8 text file under project root."""
        path = resolve_under_root(self.project_root, relative_path)
        if not path.is_file():
            return f"[error] not a file or missing: {relative_path!r}"
        max_chars = ai_agent_max_read_file_chars()
        data = path.read_bytes()
        if len(data) > max_chars * 4:
            return f"[error] file too large to read (>{max_chars * 4} bytes); request a smaller fragment"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return "[error] not valid UTF-8 text; binary files are not supported"
        cap = ai_agent_max_read_file_chars()
        if len(text) > cap:
            return text[:cap] + f"\n\n[truncated to {cap} chars]"
        return text

    def write_project_file(self, relative_path: str, content: str) -> str:
        """Write UTF-8 text under project root (creates parent dirs). Refuses .git paths."""
        path = resolve_under_root(self.project_root, relative_path)
        if ".git" in path.parts:
            return "[error] writes under .git are not allowed"
        raw = content.encode("utf-8")
        max_b = ai_agent_max_write_file_bytes()
        if len(raw) > max_b:
            return f"[error] content too large (max {max_b} bytes)"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return f"[ok] wrote {len(raw)} bytes to {relative_path!r}"

    def apply_node_patch(self, patch_json: str) -> str:
        """Merge a whitelisted JSON patch into the working draft node. Returns skip messages or ok."""
        try:
            patch = json.loads(patch_json) if patch_json.strip() else {}
        except json.JSONDecodeError as e:
            return f"[error] invalid patch_json: {e}"
        if not isinstance(patch, dict):
            return "[error] patch_json must be a JSON object"
        node = self.draft_ref["node"]
        skipped = apply_config_patch(node, patch)
        # refresh class name uniqueness hint in return only (no enforcement here)
        _ = self.existing_class_names
        summary = "applied patch to draft node."
        if skipped:
            summary += " Notes: " + "; ".join(skipped[:5])
        return "[ok] " + summary + "\n\nDraft preview (abbreviated):\n" + json.dumps(
            {
                "class_name": node.get("class_name"),
                "title": node.get("title"),
                "inputs": len(node.get("inputs") or []),
                "outputs": len(node.get("outputs") or []),
                "core_logic_lines": len(str(node.get("core_logic", "")).splitlines()),
            },
            ensure_ascii=False,
        )

    def get_node_snapshot(self) -> str:
        return json.dumps(self.draft_ref["node"], ensure_ascii=False)[:120_000]

    def run_stub_test(self, core_logic: str, cases_json: str = "[]") -> str:
        node = copy.deepcopy(self.draft_ref["node"])
        try:
            raw = json.loads(cases_json) if cases_json.strip() else []
        except json.JSONDecodeError as e:
            return f"[error] invalid cases_json: {e}"
        if not isinstance(raw, list):
            return "[error] cases_json must be a JSON array"
        cases = normalize_test_cases(raw if raw else None, node)
        summary = evaluate_stub_cases(core_logic.strip(), node, cases)
        out = json.dumps(summary, ensure_ascii=False)
        cap = ai_agent_max_tool_output_chars()
        if len(out) > cap:
            return out[:cap] + f"\n[truncated to {cap} chars]"
        return out

    def validate_core_logic_tool(self, code: str) -> str:
        """AST + forbidden-name static check."""
        if not (code or "").strip():
            return json.dumps({"ok": False, "error": "empty code"}, ensure_ascii=False)
        t = dedent_core_logic(code)
        ok, err = validate_core_logic(t)
        return json.dumps({"ok": ok, "error": err or None}, ensure_ascii=False)

    def run_shell(self, command: str) -> str:
        """Run a single guarded shell command in project root (optional; off by default)."""
        if not ai_agent_bash_enabled():
            return (
                "[error] shell is disabled. Set AI_AGENT_BASH=true in .env to enable "
                "(still subject to command guards and timeout)."
            )
        ok, reason = check_shell_command(command)
        if not ok:
            return f"[error] command rejected: {reason}"
        timeout = ai_agent_shell_timeout_sec()
        cap = ai_agent_max_tool_output_chars()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=None,
            )
        except subprocess.TimeoutExpired:
            return f"[error] command timed out after {timeout}s"
        except Exception as exc:
            return f"[error] {type(exc).__name__}: {exc}"
        out = ""
        if proc.stdout:
            out += proc.stdout
        if proc.stderr:
            out += "\n[stderr]\n" + proc.stderr
        status = f"exit_code={proc.returncode}"
        blob = f"{status}\n{out}".strip()
        if len(blob) > cap:
            return blob[:cap] + f"\n[truncated to {cap} chars]"
        return blob or f"{status} (no output)"
