"""Record one real research run as a test fixture (costs a few cents).

    cd backend
    venv/bin/python -m evals.record_fixture anthropic "Latest NVDA earnings news and its price"
    venv/bin/python -m evals.record_fixture openai "Latest NVDA earnings news and its price"

Runs the provider's LangChain agent with offline market data and saves the raw API response
bodies to tests/fixtures/langchain/<provider>_web.json. The provider's test file replays them
to check that real responses parse into a cited report. Encrypted content is replaced with a
placeholder; review the file before committing it.
"""

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import langchain_anthropic.chat_models as anthropic_chat
import langchain_openai.chat_models.base as openai_chat

from core.config import settings
from evals.fixtures import offline_market_data
from service.research.langchain_agent import (
    LangChainAnthropicAgent,
    LangChainOpenAIAgent,
    LangChainResearchAgent,
)

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "langchain"
REDACT = {"encrypted_content", "encrypted_index", "signature"}
DEFAULT_PROMPT = "Latest NVDA earnings news and its current price"
# provider -> (agent, module holding the client factory, API path, key setting)
PROVIDERS: dict[str, tuple[type[LangChainResearchAgent], Any, str, str]] = {
    "anthropic": (LangChainAnthropicAgent, anthropic_chat, "/v1/messages", "ANTHROPIC_API_KEY"),
    "openai": (LangChainOpenAIAgent, openai_chat, "/responses", "OPENAI_API_KEY"),
}


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "redacted" if k in REDACT else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def recording(factory: Callable[..., httpx2.AsyncClient], path: str, bodies: list[Any]) -> Any:
    """Wrap an SDK client factory so every API response body is also kept."""

    async def keep(response: httpx2.Response) -> None:
        if response.request.url.path.endswith(path):
            await response.aread()
            bodies.append(response.json())

    def client(*args: Any, **kwargs: Any) -> httpx2.AsyncClient:
        made = factory(*args, **kwargs)
        made.event_hooks["response"].append(keep)
        return made

    return client


async def record(provider: str, prompt: str) -> int:
    agent_class, module, path, key = PROVIDERS[provider]
    if not str(getattr(settings, key)).strip():
        print(f"Set {key} in backend/.env first.")
        return 1
    bodies: list[Any] = []
    module._get_default_async_httpx_client = recording(
        module._get_default_async_httpx_client, path, bodies
    )

    async def progress(**values: Any) -> None:
        print(f"  {values['stage']}")

    agent = agent_class(progress)
    with offline_market_data():
        report = await agent.run(prompt, [])
    out = FIXTURES / f"{provider}_web.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"prompt": prompt, "responses": scrub(bodies)}, indent=2) + "\n")
    print(f"\n{report[:600]}\n\nSaved {len(bodies)} responses to {out}")
    print(f"Tokens: {agent.input_tokens} in / {agent.output_tokens} out; review before committing.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    chosen = args.pop(0) if args and args[0] in PROVIDERS else "anthropic"
    sys.exit(asyncio.run(record(chosen, " ".join(args) or DEFAULT_PROMPT)))
