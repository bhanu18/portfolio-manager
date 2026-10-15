"""One failure table for the OpenAI/Anthropic SDKs (raised through LangChain)."""

import anthropic
import httpx2  # the SDKs' HTTP client; their exceptions need httpx2 objects
import openai
import pytest

from service.research.errors import (
    ProviderUnavailable,
    ResearchFailure,
    provider_failure,
)

CASES = [
    (400, {"error": {"message": "Your credit balance is too low"}}, True, 1800),
    (402, {"error": "payment required"}, True, 1800),
    (429, {"error": {"code": "insufficient_quota"}}, True, 1800),
    (429, {"error": "rate limited"}, True, 60),
    (401, {"error": "bad key"}, True, 1800),
    (403, {"error": "no model access"}, True, 1800),
    (529, {"error": "overloaded"}, True, 60),
    (400, {"error": "SECRET bad schema"}, False, None),
]


def sdk_error(module, status, body):
    request = httpx2.Request("POST", "https://api.example.com")
    response = httpx2.Response(status, json=body, request=request)
    error = module.APIStatusError("x", response=response, body=body)
    return provider_failure(error, "P")


SOURCES = {
    "openai": lambda status, body: sdk_error(openai, status, body),
    "anthropic": lambda status, body: sdk_error(anthropic, status, body),
}


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize(("status", "body", "unavailable", "cooldown"), CASES)
def test_same_classification_for_every_client(source, status, body, unavailable, cooldown):
    failure = SOURCES[source](status, body)
    assert isinstance(failure, ResearchFailure)
    assert isinstance(failure, ProviderUnavailable) is unavailable
    assert getattr(failure, "cooldown", None) == cooldown
    assert "SECRET" not in str(failure)  # upstream bodies are never shown to users


@pytest.mark.parametrize("module", [openai, anthropic])
def test_connection_errors_and_timeouts_are_outages(module):
    request = httpx2.Request("POST", "https://api.example.com")
    for error in (module.APIConnectionError(request=request), module.APITimeoutError(request)):
        failure = provider_failure(error, "P")
        assert isinstance(failure, ProviderUnavailable) and failure.cooldown == 60


def test_unrelated_errors_are_not_disguised_as_outages():
    with pytest.raises(KeyError):
        provider_failure(KeyError("bug"), "P")


def test_custom_rejection_message():
    request = httpx2.Request("POST", "https://api.example.com")
    response = httpx2.Response(400, json={}, request=request)
    error = anthropic.APIStatusError("x", response=response, body={})
    assert str(provider_failure(error, "P", rejected="Pick another model.")) == (
        "Pick another model."
    )
