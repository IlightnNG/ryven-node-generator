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
    def validate_core_logic_tool(code: str = "") -> str:
        """Static-check Python node body: AST + forbidden names. Returns JSON {ok, error}.

        Pass empty string to validate the draft node's core_logic (after apply_node_patch)."""
        return host.validate_core_logic_tool(code)

    @tool
    def run_stub_test(core_logic: str = "", cases_json: str = "[]") -> str:
        """Run stub tests. Pass empty core_logic to use the draft body; cases_json is a JSON array of cases."""
        return host.run_stub_test(core_logic, cases_json)

    @tool
    def compress_conversation_context(summary_of_older_turns: str, keep_last_messages: int = 8) -> str:
        """When prior chat is too long, summarize dropped older turns and keep the last N messages before this request.

        Call before more tools if the model context is huge. The orchestrator replaces older history with your summary."""
        return host.compress_conversation_context_placeholder(summary_of_older_turns, keep_last_messages)

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

        **Argument types (strict):** follow the tool JSON schema. For "no change", **omit** the
        optional field or use JSON **null** — never pass an empty string `""` for `core_logic`,
        `config_patch`, or `self_test_cases`.

        Include a full `config_patch` object when ports or metadata changed: complete `inputs` /
        `outputs` lists (labels, types, widgets), plus `class_name`, `title`, `description`, `color`,
        and main-widget fields as needed — not only `core_logic`."""
        return "handled_by_orchestrator"

    return [
        get_node_snapshot,
        read_project_file,
        write_project_file,
        apply_node_patch,
        validate_core_logic_tool,
        run_stub_test,
        compress_conversation_context,
        run_shell,
        submit_node_turn,
    ]
