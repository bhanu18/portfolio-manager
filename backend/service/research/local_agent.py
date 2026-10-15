"""Local-model helpers (Ollama, LM Studio, vLLM, mlx_lm via their OpenAI-compatible API).

The research loop for local models is `LangChainLocalAgent` in `langchain_agent.py`; this
module holds what both it and the routing/import code share.
"""

import json
import re
from typing import Any

import openai
from langchain_core.messages import HumanMessage, SystemMessage

from core.config import settings
from service.research.models import chat_model

NO_WEB = (
    "Web search is unavailable for this model. Use only the read-only tools and data provided; "
    "say plainly when news or other web-only information was not retrieved."
)
# Reasoning models (qwen3, deepseek-r1) may inline their thinking in the content.
THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    return THINK.sub("", text).strip()


async def local_json(
    system: str, prompt: str, *, max_tokens: int = 300, model: str | None = None
) -> tuple[dict[str, Any] | None, int, int]:
    """One JSON-mode call for cheap routing decisions. Returns (data, input, output tokens).

    Never raises: callers fall back to deterministic rules when the local model is unavailable.
    """
    model = (model or settings.LOCAL_LLM_MODEL).strip()
    if not model:
        return None, 0, 0
    # Routing needs no reasoning; thinking would exhaust max_tokens first.
    llm = chat_model("local", model, max_tokens=max_tokens, thinking=False, timeout=30).bind(
        response_format={"type": "json_object"}, temperature=0
    )
    try:
        message = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        usage = getattr(message, "usage_metadata", None) or {}
        tokens = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        content = strip_thinking(message.text)
        # Servers without JSON mode (e.g. mlx_lm.server) may wrap the object in prose or fences.
        start, end = content.find("{"), content.rfind("}")
        parsed = json.loads(content[start : end + 1] if 0 <= start < end else content)
        return (parsed if isinstance(parsed, dict) else None), *tokens
    except (openai.APIError, ValueError, KeyError, IndexError, TypeError):
        return None, 0, 0
