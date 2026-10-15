"""LangSmith tracing for research runs. Off unless LANGSMITH_TRACING and a key are set.

Settings come from pydantic (`core.config`), not the process environment, so they are
applied with `langsmith.configure` once per process (worker or eval runner).
"""

import logging
from typing import Any

import langsmith
from langsmith import Client
from langsmith.run_helpers import get_current_run_tree

from core.config import settings

logger = logging.getLogger(__name__)
_client: Client | None = None


def tracing_enabled() -> bool:
    return settings.LANGSMITH_TRACING and bool(settings.LANGSMITH_API_KEY.strip())


def langsmith_client() -> Client:
    """One client per process, built from settings (shared by tracing and evals)."""
    global _client
    if _client is None:
        _client = Client(
            api_url=settings.LANGSMITH_ENDPOINT,
            api_key=settings.LANGSMITH_API_KEY.strip() or None,
            hide_inputs=settings.LANGSMITH_HIDE_INPUTS,
            hide_outputs=settings.LANGSMITH_HIDE_OUTPUTS,
        )
    return _client


def configure_tracing() -> bool:
    """Apply settings globally. Explicitly disables tracing when off, so a stray
    LANGSMITH_TRACING in the shell cannot leak user questions."""
    if not tracing_enabled():
        langsmith.configure(enabled=False)
        return False
    langsmith.configure(
        client=langsmith_client(),
        enabled=True,
        project_name=settings.LANGSMITH_PROJECT,
    )
    logger.info("LangSmith tracing enabled (project %s)", settings.LANGSMITH_PROJECT)
    return True


def flush_traces() -> None:
    """Send buffered runs before the process exits; never fails the caller."""
    if _client is None:
        return
    try:
        _client.flush()
    except Exception:
        logger.exception("Could not flush LangSmith traces")


def annotate(*, metadata: dict[str, Any] | None = None, **outputs: Any) -> None:
    """Attach metadata/outputs to the current traced run; a no-op when not tracing."""
    run = get_current_run_tree()
    if run is None:
        return
    if metadata:
        run.add_metadata(metadata)
    if outputs:
        run.add_outputs(outputs)


def usage_metadata(input_tokens: int, output_tokens: int) -> dict[str, int]:
    """LangSmith's token-count shape (rolled up per trace in the UI)."""
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
