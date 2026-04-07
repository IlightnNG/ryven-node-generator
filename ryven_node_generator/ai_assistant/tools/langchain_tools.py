"""LangChain @tool wrappers bound to a :class:`ReactToolHost`."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from .host import ReactToolHost


def build_langchain_tools(host: ReactToolHost) -> list[Any]:
    @tool
    def get_node_snapshot() -> str:
        """Return the current working node JSON (ports, labels, core_logic draft)."""
        return host.get_node_snapshot()

    @tool
    def read_project_file(relative_path: str) -> str:
        """Read a UTF-8 text file under the project root. Pass a relative path (e.g. docs/agent-refactor-roadmap-for-ai.md)."""
        return host.read_project_file(relative_path)

    @tool
    def write_project_file(relative_path: str, content: str) -> str:
        """Write UTF-8 text under the project root (creates parent dirs). Do not use for secrets."""
        return host.write_project_file(relative_path, content)

    @tool
    def apply_node_patch(patch_json: str) -> str:
        """Merge a JSON object into the draft Ryven node (whitelist keys: class_name, title, inputs, outputs, core_logic, ...)."""
        return host.apply_node_patch(patch_json)

    @tool
    def validate_core_logic_tool(code: str) -> str:
        """Static-check Python node body: AST + forbidden names. Returns JSON {ok, error}."""
        return host.validate_core_logic_tool(code)

    @tool
    def run_stub_test(core_logic: str, cases_json: str = "[]") -> str:
        """Run stub tests: core_logic string and cases_json as JSON array of {inputs, expected_outputs, note}."""
        return host.run_stub_test(core_logic, cases_json)

    @tool
    def run_shell(command: str) -> str:
        """Run one guarded shell command with cwd=project root. Disabled unless AI_AGENT_BASH=true."""
        return host.run_shell(command)

    @tool
    def submit_node_turn(
        message: str,
        core_logic: str | None = None,
        config_patch: dict[str, Any] | None = None,
        self_test_cases: list[dict[str, Any]] | None = None,
    ) -> str:
        """Finalize the node. Call once when done.

        Include a full `config_patch` when ports or metadata changed: complete `inputs` / `outputs`
        lists (labels, types, widgets), plus `class_name`, `title`, `description`, `color`, and
        main-widget fields as needed — not only `core_logic`."""
        return "handled_by_orchestrator"

    return [
        get_node_snapshot,
        read_project_file,
        write_project_file,
        apply_node_patch,
        validate_core_logic_tool,
        run_stub_test,
        run_shell,
        submit_node_turn,
    ]
