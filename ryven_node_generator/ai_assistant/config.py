"""Load .env and OpenAI-compatible settings (OpenAI official or Alibaba Bailian DashScope)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Package root: ryven_node_generator/; repo root is one level above.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# DashScope OpenAI-compatible base URLs by region (see Alibaba Model Studio docs)
_DASHSCOPE_BASE = {
    "beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "us": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "hongkong": "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
}


def default_agent_project_root() -> Path:
    """When no workspace is open, tools use the generator repository root."""
    return _REPO_ROOT.resolve()


def load_env() -> None:
    """Load repository-root `.env`, then parent directory `.env` (later overrides)."""
    load_dotenv(_REPO_ROOT / ".env", override=False)
    parent_env = _REPO_ROOT.parent / ".env"
    if parent_env.is_file():
        load_dotenv(parent_env, override=True)


def get_llm_provider() -> str:
    """Return 'openai' or 'dashscope' (Bailian)."""
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p in ("dashscope", "bailian", "aliyun", "qwen"):
        return "dashscope"
    return "openai"


def get_dashscope_region() -> str:
    r = os.getenv("DASHSCOPE_REGION", "beijing").strip().lower()
    if r in ("cn", "cn-beijing", "beijing", "default"):
        return "beijing"
    if r in ("intl", "singapore", "sg", "ap-southeast"):
        return "singapore"
    if r in ("us", "virginia", "us-east"):
        return "us"
    if r in ("hk", "hongkong", "cn-hongkong"):
        return "hongkong"
    return "beijing"


def _default_dashscope_base_url() -> str:
    return _DASHSCOPE_BASE.get(get_dashscope_region(), _DASHSCOPE_BASE["beijing"])


def is_dashscope_compatible_url(url: str | None) -> bool:
    if not url:
        return False
    u = url.lower()
    return "dashscope" in u and "compatible-mode" in u


def get_openai_api_key() -> str | None:
    """Bailian keys may be set as DASHSCOPE_API_KEY or OPENAI_API_KEY."""
    for name in ("DASHSCOPE_API_KEY", "OPENAI_API_KEY"):
        k = os.getenv(name, "").strip()
        if k:
            return k
    return None


def get_model_name() -> str:
    m = os.getenv("OPENAI_MODEL", "").strip()
    if m:
        return m
    if get_llm_provider() == "dashscope":
        return "qwen3.5-flash"
    return "gpt-4o-mini"


def get_temperature() -> float:
    try:
        return float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    except ValueError:
        return 0.2


def get_base_url() -> str | None:
    u = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
    if u:
        return u
    if get_llm_provider() == "dashscope":
        return _default_dashscope_base_url()
    return None


def use_json_prompt_for_structured() -> bool:
    """
    Some DashScope models handle OpenAI tool/function calling inconsistently; default to JSON text.
    STRUCTURED_OUTPUT_MODE=json_prompt | function_calling | auto
    """
    mode = os.getenv("STRUCTURED_OUTPUT_MODE", "auto").strip().lower()
    if mode == "json_prompt":
        return True
    if mode == "function_calling":
        return False
    bu = get_base_url()
    if bu and is_dashscope_compatible_url(bu):
        return True
    return get_llm_provider() == "dashscope"


def ai_stream_enabled() -> bool:
    """Stream assistant-visible text when True (default). Set AI_STREAM=false to disable."""
    return os.getenv("AI_STREAM", "true").strip().lower() not in ("0", "false", "no", "off")


def ai_agent_mode() -> str:
    """``react`` (default): ReAct tool loop + submit_node_turn. ``legacy``: single-turn <<<JSON>>> / structured output without tools."""
    m = os.getenv("AI_AGENT_MODE", "react").strip().lower()
    if m in ("legacy", "single", "single_turn"):
        return "legacy"
    return "react"


def ai_context_max_user_assistant_messages() -> int:
    """Max prior **user + assistant** chat messages sent to the LLM per request.

    ``0`` = unlimited (full history). Default ``48`` (~24 rounds). UI ``system`` rows are not counted.
    """
    raw = os.getenv("AI_CONTEXT_MAX_MESSAGES", "48").strip()
    try:
        v = int(raw)
    except ValueError:
        return 48
    if v <= 0:
        return 0
    return min(500, v)


def ai_context_max_chars_per_message() -> int:
    """Max characters per prior user/assistant message body (after count trim).

    ``0`` = unlimited. Default ``12000`` keeps long assistant rants from blowing the context.
    """
    raw = os.getenv("AI_CONTEXT_MAX_CHARS_PER_MESSAGE", "12000").strip()
    try:
        v = int(raw)
    except ValueError:
        return 12_000
    if v <= 0:
        return 0
    return min(500_000, v)


def ai_agent_session_log_path(project_root: str | None) -> Path | None:
    """If ``AI_AGENT_SESSION_LOG`` is set, append JSONL lines to this file (ReAct debug).

    Relative paths resolve under ``project_root`` when given, else under :func:`default_agent_project_root`.
    Empty / unset → no file logging.
    """
    raw = os.getenv("AI_AGENT_SESSION_LOG", "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()
    base = Path(project_root).expanduser().resolve() if project_root else default_agent_project_root()
    return (base / p).resolve()


def ai_agent_session_log_field_chars() -> int:
    """Max characters per message field / tool result blob in the session log (default 250k)."""
    try:
        v = int(os.getenv("AI_AGENT_SESSION_LOG_FIELD_CHARS", "250000").strip())
    except ValueError:
        return 250_000
    return max(5_000, min(2_000_000, v))


def ai_context_compact_node_json() -> bool:
    """When true (default), node JSON in the context system message is minified (no indent)."""
    return os.getenv("AI_CONTEXT_COMPACT_JSON", "true").strip().lower() not in ("0", "false", "no", "off")


def ai_agent_max_steps() -> int:
    """Max model steps in ReAct loop (each step may include multiple tool calls). Clamped to [1, 64]."""
    raw = os.getenv("AI_AGENT_MAX_STEPS", "24").strip()
    try:
        value = int(raw)
    except ValueError:
        return 24
    return max(1, min(64, value))


def ai_agent_bash_enabled() -> bool:
    """Allow run_shell tool when true (default false)."""
    return os.getenv("AI_AGENT_BASH", "false").strip().lower() in ("1", "true", "yes", "on")


def ai_agent_max_read_file_chars() -> int:
    try:
        v = int(os.getenv("AI_AGENT_MAX_READ_CHARS", "200000").strip())
    except ValueError:
        return 200_000
    return max(1_000, min(500_000, v))


def ai_agent_max_write_file_bytes() -> int:
    try:
        v = int(os.getenv("AI_AGENT_MAX_WRITE_BYTES", "512000").strip())
    except ValueError:
        return 512_000
    return max(1_000, min(2_000_000, v))


def ai_agent_max_tool_output_chars() -> int:
    try:
        v = int(os.getenv("AI_AGENT_MAX_TOOL_OUTPUT_CHARS", "32000").strip())
    except ValueError:
        return 32_000
    return max(2_000, min(200_000, v))


def ai_agent_shell_timeout_sec() -> int:
    try:
        v = int(os.getenv("AI_AGENT_SHELL_TIMEOUT", "45").strip())
    except ValueError:
        return 45
    return max(5, min(120, v))
