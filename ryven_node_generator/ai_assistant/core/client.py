"""Build provider-compatible ChatOpenAI client for assistant turns."""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from ..config import get_base_url, get_model_name, get_openai_api_key, get_temperature


def build_chat_model() -> ChatOpenAI:
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "API key missing. Set DASHSCOPE_API_KEY or OPENAI_API_KEY in .env. "
            "For Alibaba Bailian, set LLM_PROVIDER=dashscope or set OPENAI_BASE_URL to a compatible-mode endpoint."
        )

    kwargs: dict[str, Any] = {
        "model": get_model_name(),
        "temperature": get_temperature(),
        "api_key": api_key,
    }

    base_url = get_base_url()
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)
