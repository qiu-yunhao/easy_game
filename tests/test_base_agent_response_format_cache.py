from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from BaseAgent import BaseAgent


class _RecordingClient:
    """Fake OpenAI client: rejects structured response_format like DeepSeek,
    records how many requests were sent and whether each carried a schema."""

    def __init__(self) -> None:
        self.requests: list[bool] = []  # True if request carried response_format
        self.formats: list = []  # full response_format value per request
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    def _create(self, **params):
        rf = params.get("response_format")
        self.formats.append(rf)
        has_rf = rf is not None
        self.requests.append(has_rf)
        if has_rf and rf.get("type") == "json_schema":
            raise RuntimeError("response_format json_schema is unavailable on this endpoint")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"ok": True})))]
        )


SCHEMA = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}}


@pytest.fixture(autouse=True)
def _reset_endpoint_cache():
    BaseAgent._response_format_unsupported.clear()
    yield
    BaseAgent._response_format_unsupported.clear()


def _make_agent(client):
    return BaseAgent(base_url="https://fake.endpoint", model="stub", client=client)


def test_first_structured_call_probes_then_falls_back():
    client = _RecordingClient()
    agent = _make_agent(client)
    result = agent.command("hi", response_format=SCHEMA)
    assert result == {"ok": True}
    # First call: one failed json_schema request + one json_object fallback request.
    assert client.formats == [SCHEMA, {"type": "json_object"}]
    assert "https://fake.endpoint" in BaseAgent._response_format_unsupported


def test_fallback_uses_json_object_not_bare():
    client = _RecordingClient()
    agent = _make_agent(client)
    agent.command("hi", response_format=SCHEMA)
    assert client.formats == [SCHEMA, {"type": "json_object"}]


def test_subsequent_calls_skip_the_doomed_first_request():
    client = _RecordingClient()
    agent = _make_agent(client)
    agent.command("first", response_format=SCHEMA)
    client.formats.clear()
    agent.command("second", response_format=SCHEMA)
    # Endpoint is now known-unsupported: go straight to the json_object fallback.
    assert client.formats == [{"type": "json_object"}]


def test_cache_is_shared_across_agent_instances_on_same_endpoint():
    client_a = _RecordingClient()
    agent_a = _make_agent(client_a)
    agent_a.command("warm", response_format=SCHEMA)

    client_b = _RecordingClient()
    agent_b = _make_agent(client_b)
    client_b.formats.clear()
    agent_b.command("go", response_format=SCHEMA)
    assert client_b.formats == [{"type": "json_object"}]
