"""LangChain model factory: settings only, no network."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from core.config import settings
from service.research.errors import ProviderUnavailable
from service.research.models import LOCAL_PLACEHOLDER_KEY, chat_model


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(settings, "LOCAL_LLM_API_KEY", "ollama")
    monkeypatch.setattr(settings, "LOCAL_LLM_THINKING", False)


@pytest.mark.parametrize("provider", ["anthropic", "openai", "local"])
def test_failover_owns_retries_and_blocks_are_standard(provider):
    model = chat_model(provider, "some-model", max_tokens=1234)
    assert model.max_retries == 0
    assert model.output_version == "v1"
    # Local servers read `max_tokens` from the body (see test_local_model_body).
    limit = model.extra_body["max_tokens"] if provider == "local" else model.max_tokens
    assert limit == 1234


def test_anthropic():
    model = chat_model("anthropic", "claude-sonnet-5-5", max_tokens=100)
    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-sonnet-5-5"
    assert model.anthropic_api_key.get_secret_value() == "sk-ant-test"


def test_openai_uses_stateless_responses_api():
    model = chat_model("openai", "gpt-5-mini", max_tokens=100)
    assert isinstance(model, ChatOpenAI)
    assert (model.use_responses_api, model.store) == (True, False)
    assert "web_search_call.action.sources" in (model.include or [])


def test_local_uses_openai_compatible_server(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://localhost:8080/v1")
    model = chat_model("local", "qwen3:8b", max_tokens=100)
    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == "http://localhost:8080/v1"
    assert model.use_responses_api is False
    assert model.extra_body == {
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 100,
    }
    forced = chat_model("local", "qwen3:8b", max_tokens=100, thinking=True)
    assert forced.extra_body["chat_template_kwargs"] == {"enable_thinking": True}


def test_local_without_key_sends_placeholder(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_LLM_API_KEY", " ")
    model = chat_model("local", "qwen3:8b", max_tokens=100)
    assert model.openai_api_key.get_secret_value() == LOCAL_PLACEHOLDER_KEY


@pytest.mark.parametrize(
    ("provider", "setting"), [("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")]
)
def test_missing_cloud_key_fails_over_like_a_401(provider, setting, monkeypatch):
    monkeypatch.setattr(settings, setting, "")
    with pytest.raises(ProviderUnavailable) as raised:
        chat_model(provider, "m", max_tokens=100)
    assert raised.value.cooldown == 1800


def test_unknown_provider():
    with pytest.raises(ValueError, match="Unknown research provider"):
        chat_model("gemini", "m", max_tokens=100)
