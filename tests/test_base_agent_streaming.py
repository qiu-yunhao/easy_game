from __future__ import annotations

from types import SimpleNamespace

from BaseAgent import BaseAgent


def _chunk(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class _StreamingClient:
    """Fake client: yields token chunks when stream=True, else one full message."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.stream_requested: list[bool] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.stream_requested.append(bool(params.get("stream")))
        if params.get("stream"):
            return iter([_chunk(t) for t in self._tokens])
        full = "".join(self._tokens)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=full))])


def _make_agent(client):
    return BaseAgent(base_url="https://fake.endpoint", model="stub", client=client)


def test_on_token_streams_deltas_and_returns_full_text():
    client = _StreamingClient(["修", "士", "抬", "眼"])
    agent = _make_agent(client)
    seen: list[str] = []

    result = agent.command("narrate", on_token=seen.append)

    assert result == "修士抬眼"
    assert seen == ["修", "士", "抬", "眼"]
    assert client.stream_requested == [True]


def test_without_on_token_stays_non_streaming():
    client = _StreamingClient(["a", "b"])
    agent = _make_agent(client)

    result = agent.command("narrate")

    assert result == "ab"
    assert client.stream_requested == [False]


def test_structured_output_never_streams_even_with_on_token():
    client = _StreamingClient(['{"ok": true}'])
    agent = _make_agent(client)
    seen: list[str] = []

    result = agent.command("plan", response_format="json", on_token=seen.append)

    assert result == {"ok": True}
    assert seen == []
    assert client.stream_requested == [False]
