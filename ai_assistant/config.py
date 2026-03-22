"""Load .env and OpenAI-compatible settings (OpenAI official or Alibaba Bailian DashScope)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_GENERATOR_DIR = Path(__file__).resolve().parent.parent

# DashScope OpenAI-compatible base URLs by region (see Alibaba Model Studio docs)
_DASHSCOPE_BASE = {
    "beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "us": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "hongkong": "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
}


def load_env() -> None:
    """Load Generator/.env, then repository-root .env (later file overrides)."""
    load_dotenv(_GENERATOR_DIR / ".env", override=False)
    root = _GENERATOR_DIR.parent / ".env"
    if root.is_file():
        load_dotenv(root, override=True)


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
