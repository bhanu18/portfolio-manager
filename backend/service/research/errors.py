"""Research errors and the one table that maps provider failures to them.

Shared by the httpx adapters (`http_failure`) and LangChain models (`provider_failure`), so
failover and cooldowns behave the same whichever client made the call.
"""

import httpx


class ResearchFailure(Exception):
    """Safe, actionable error that may be shown to a user."""


class ProviderUnavailable(ResearchFailure):
    """The provider cannot serve any request right now (credit, key, rate limit, outage).

    Unlike other failures this says nothing about the question, so Auto fails over to
    another model and skips this provider for `cooldown` seconds.
    """

    def __init__(self, message: str, *, cooldown: float):
        super().__init__(message)
        self.cooldown = cooldown


# Matched against the upstream error body, which is never shown to users. Anthropic reports
# an exhausted balance as a 400 and OpenAI as a 429 `insufficient_quota`.
CREDIT_HINTS = ("credit balance", "billing", "quota", "payment", "insufficient")


def classify_failure(
    status: int | None, body: str, name: str, rejected: str | None = None
) -> ResearchFailure:
    """Map a provider status (None = unreachable) and lowercased error body to a safe error."""
    if status is None:
        return ProviderUnavailable(f"{name} could not be reached. Please retry later.", cooldown=60)
    if status == 402 or any(hint in body for hint in CREDIT_HINTS):
        return ProviderUnavailable(
            f"{name}'s credit or billing limit was reached. Check API billing.", cooldown=1800
        )
    if status in (401, 403):
        return ProviderUnavailable(
            f"The {name} API key or model access needs attention on the server.", cooldown=1800
        )
    if status == 429:
        return ProviderUnavailable(f"{name}'s rate limit was reached. Retry later.", cooldown=60)
    if status >= 500:
        return ProviderUnavailable(f"{name} is temporarily unavailable. Retry later.", cooldown=60)
    return ResearchFailure(
        rejected or f"{name} rejected the request. Check model configuration and retry."
    )


def http_failure(error: httpx.HTTPError, name: str, rejected: str | None = None) -> ResearchFailure:
    """Map a provider HTTP error to a safe message, flagging errors worth failing over."""
    if not isinstance(error, httpx.HTTPStatusError):
        return classify_failure(None, "", name, rejected)
    body = error.response.text[:2000].lower()
    return classify_failure(error.response.status_code, body, name, rejected)


def provider_failure(error: Exception, name: str, rejected: str | None = None) -> ResearchFailure:
    """Map an OpenAI/Anthropic SDK error (as raised through LangChain) to a safe error.

    Anything else is re-raised: a bug must never look like a provider outage.
    """
    # Imported here so modules that only need the exception classes stay light.
    import anthropic
    import openai

    if isinstance(error, openai.APIConnectionError | anthropic.APIConnectionError):
        return classify_failure(None, "", name, rejected)  # includes timeouts
    if isinstance(error, openai.APIStatusError | anthropic.APIStatusError):
        body = error.response.text[:2000].lower()
        return classify_failure(error.status_code, body, name, rejected)
    raise error
