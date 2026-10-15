"""Record one real Anthropic research run as a test fixture (costs a few cents).

    cd backend
    venv/bin/python -m evals.record_fixture "Latest NVDA earnings news and its current price"

Runs `LangChainAnthropicAgent` with offline market data and saves the raw Messages API
response bodies to tests/fixtures/langchain/anthropic_web.json. `test_langchain_agent.py`
replays them to check that real responses parse into a cited report. Encrypted search content
is replaced with a placeholder; review the file before committing it.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx2
import langchain_anthropic.chat_models as anthropic_chat

from core.config import settings
from evals.fixtures import offline_market_data
from service.research.langchain_agent import LangChainAnthropicAgent

OUT = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "langchain" / "anthropic_web.json"
)
REDACT = {"encrypted_content", "encrypted_index", "signature"}


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "redacted" if k in REDACT else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


async def record(prompt: str) -> int:
    if not settings.ANTHROPIC_API_KEY.strip():
        print("Set ANTHROPIC_API_KEY in backend/.env first.")
        return 1
    bodies: list[dict[str, Any]] = []

    async def keep(response: httpx2.Response) -> None:
        if response.request.url.path.endswith("/v1/messages"):
            await response.aread()
            bodies.append(response.json())

    original = anthropic_chat._get_default_async_httpx_client

    def recording_client(**params: Any) -> httpx2.AsyncClient:
        client = original(**params)
        client.event_hooks["response"].append(keep)
        return client

    anthropic_chat._get_default_async_httpx_client = recording_client  # type: ignore[assignment]

    async def progress(**values: Any) -> None:
        print(f"  {values['stage']}")

    agent = LangChainAnthropicAgent(progress)
    with offline_market_data():
        report = await agent.run(prompt, [])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"prompt": prompt, "responses": scrub(bodies)}, indent=2) + "\n")
    print(f"\n{report[:600]}\n\nSaved {len(bodies)} responses to {OUT}")
    print(f"Tokens: {agent.input_tokens} in / {agent.output_tokens} out; review before committing.")
    return 0


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Latest NVDA earnings news and its current price"
    sys.exit(asyncio.run(record(question)))
