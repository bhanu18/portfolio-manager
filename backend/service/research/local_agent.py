"""OpenAI-compatible Chat Completions adapter for local models (Ollama, LM Studio, vLLM)."""

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from core.config import settings
from service.research.agent import TOOLS, ProviderUnavailable, ResearchAgent, ResearchFailure

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        },
    }
    for tool in TOOLS
    if tool["type"] == "function"
]
NO_WEB = (
    "Web search is unavailable for this model. Use only the read-only tools and data provided; "
    "say plainly when news or other web-only information was not retrieved."
)
# Reasoning models (qwen3, deepseek-r1) may inline their thinking in the content.
THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def local_url(path: str) -> str:
    return settings.LOCAL_LLM_BASE_URL.rstrip("/") + path


def local_headers() -> dict[str, str]:
    # Local servers (Ollama, mlx_lm.server) need no key; an empty "Bearer " is an illegal header.
    key = settings.LOCAL_LLM_API_KEY.strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def thinking(enabled: bool) -> dict[str, Any]:
    """Toggle reasoning on thinking models (Gemma 4, Qwen3) via the chat template.

    Honoured by mlx_lm.server, vLLM and LM Studio; servers that don't know it ignore it.
    """
    return {"chat_template_kwargs": {"enable_thinking": enabled}}


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
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=3)) as client:
            response = await client.post(
                local_url("/chat/completions"),
                headers=local_headers(),
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    # Routing needs no reasoning; thinking would exhaust max_tokens first.
                    **thinking(False),
                },
            )
            response.raise_for_status()
            data = response.json()
        usage = data.get("usage") or {}
        tokens = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        content = strip_thinking(data["choices"][0]["message"].get("content") or "")
        # Servers without JSON mode (e.g. mlx_lm.server) may wrap the object in prose or fences.
        start, end = content.find("{"), content.rfind("}")
        parsed = json.loads(content[start : end + 1] if 0 <= start < end else content)
        return (parsed if isinstance(parsed, dict) else None), *tokens
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None, 0, 0


class LocalResearchAgent(ResearchAgent):
    def __init__(
        self, progress: Callable[..., Awaitable[None]], *, model: str | None = None, **options: Any
    ):
        super().__init__(progress, model=model or settings.LOCAL_LLM_MODEL, **options)

    def instructions(self) -> str:
        return f"{super().instructions()}\n\n{NO_WEB}"

    async def run(self, prompt: str, history: list[dict[str, str]]) -> str:
        messages: list[dict[str, Any]] = [*history, {"role": "user", "content": prompt}]
        while (
            len(messages) > 1
            and len(json.dumps(messages, ensure_ascii=False).encode())
            > settings.RESEARCH_MAX_INPUT_TOKENS // 2
        ):
            del messages[: min(2, len(messages) - 1)]
        messages.insert(0, {"role": "system", "content": self.instructions()})
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=3)) as client:
            for _ in range(settings.RESEARCH_MAX_MODEL_TURNS):
                remaining_tools = settings.RESEARCH_MAX_TOOL_CALLS - self.tool_calls
                remaining_output = self.output_budget - self.output_tokens
                if remaining_output < 500:
                    raise ResearchFailure(
                        "The response token budget was reached. Retry with a narrower question."
                    )
                tools = (
                    [tool for tool in CHAT_TOOLS if self.tool_allowed(tool["function"]["name"])]
                    if remaining_tools > 0
                    else []
                )
                bound = len(
                    json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode()
                )
                if self.input_tokens + bound > settings.RESEARCH_MAX_INPUT_TOKENS:
                    raise ResearchFailure(
                        "The research context budget was reached. Try a narrower question or a new session."
                    )
                self.model_turns += 1
                await self.checkpoint("Drafting analysis with the local model")
                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": min(4000, remaining_output),
                    **thinking(settings.LOCAL_LLM_THINKING),
                }
                if tools:
                    payload["tools"] = tools
                try:
                    response = await client.post(
                        local_url("/chat/completions"), headers=local_headers(), json=payload
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    if error.response.status_code == 404:
                        raise ProviderUnavailable(
                            f"The local model '{self.model}' was not found. Pull it first (e.g. `ollama pull {self.model}`).",
                            cooldown=300,
                        ) from None
                    if error.response.status_code >= 500:
                        raise ProviderUnavailable(
                            "The local model server failed. Check its logs.", cooldown=60
                        ) from None
                    raise ResearchFailure(
                        "The local model server rejected the request. Check LOCAL_LLM_MODEL and server logs."
                    ) from None
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    raise ProviderUnavailable(
                        "The local model server could not be reached. Is it running at LOCAL_LLM_BASE_URL?",
                        cooldown=60,
                    ) from None
                except httpx.TimeoutException:
                    raise ProviderUnavailable(
                        "The local model took too long to answer. Try a smaller model or narrower question.",
                        cooldown=60,
                    ) from None
                except httpx.HTTPError as error:
                    raise ProviderUnavailable(
                        f"The request to the local model server failed ({type(error).__name__}).",
                        cooldown=60,
                    ) from None
                data = response.json()
                usage = data.get("usage") or {}
                self.input_tokens += int(usage.get("prompt_tokens", bound))
                self.output_tokens += int(
                    usage.get("completion_tokens", min(4000, remaining_output))
                )
                choices = data.get("choices") or []
                if not choices:
                    raise ResearchFailure("The local model returned no answer. Please retry.")
                message = choices[0].get("message") or {}
                calls = message.get("tool_calls") or []
                await self.checkpoint("Verifying sources")
                if calls:
                    self.tool_calls += len(calls)
                    if self.tool_calls > settings.RESEARCH_MAX_TOOL_CALLS:
                        raise ResearchFailure(
                            "The tool-call budget was reached. Retry with a narrower question."
                        )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": message.get("content") or "",
                            "tool_calls": calls,
                        }
                    )
                    for call in calls:
                        function = call.get("function") or {}
                        arguments = function.get("arguments", "{}")
                        result = await self.execute_tool(
                            {
                                "name": function.get("name"),
                                # Some servers return parsed objects instead of JSON strings.
                                "arguments": arguments
                                if isinstance(arguments, str)
                                else json.dumps(arguments),
                            }
                        )
                        messages.append(
                            {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
                        )
                    continue
                if choices[0].get("finish_reason") == "length":
                    raise ResearchFailure(
                        "The local model spent its output budget thinking. Set LOCAL_LLM_THINKING=false or raise RESEARCH_MAX_OUTPUT_TOKENS."
                        if message.get("reasoning") and not message.get("content")
                        else "The local model ran out of output tokens. Try a narrower question."
                    )
                report = strip_thinking(message.get("content") or "")
                if not report and message.get("reasoning"):
                    raise ResearchFailure(
                        "The local model spent its output budget thinking. Set LOCAL_LLM_THINKING=false or raise RESEARCH_MAX_OUTPUT_TOKENS."
                    )
                if not report:
                    raise ResearchFailure("The local model returned no report. Please retry.")
                if not self.evidence:
                    report = "No external evidence was retrieved for this response.\n\n" + report
                return report
        raise ResearchFailure(
            "The research turn limit was reached. Saved evidence is available; try a narrower question."
        )
