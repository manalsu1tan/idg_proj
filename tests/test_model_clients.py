from __future__ import annotations

import json

from packages.memory_core.model_components import build_model_client
from packages.memory_core.model_clients import OpenAICompatibleClient
from packages.memory_core.settings import Settings
from packages.schemas.models import ModelProvider


class DummyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_openai_compatible_client_uses_responses_api(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse({"output_text": json_module.dumps({"text": "hello", "entities": [], "topics": [], "confidence": 0.8, "citations": []})})

    json_module = json
    monkeypatch.setattr("packages.memory_core.model_clients.httpx.post", fake_post)
    client = OpenAICompatibleClient(base_url="https://api.openai.com/v1", api_key="test-key", timeout_seconds=12)
    response = client.generate_json(
        component="summarizer",
        model_name="gpt-4o-mini",
        system_prompt="Summarize this.",
        user_payload={"child_nodes": [{"node_id": "1", "text": "Memory"}]},
    )
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["json"]["text"]["format"]["type"] == "json_schema"
    assert captured["json"]["model"] == "gpt-4o-mini"
    assert captured["json"]["instructions"] == "Summarize this."
    assert isinstance(captured["json"]["input"], str)
    assert response["text"] == "hello"


def test_missing_api_key_falls_back_to_mock_provider() -> None:
    client, provider = build_model_client(
        Settings(
            model_provider="openai_compatible",
            model_api_key="",
        )
    )
    assert provider == ModelProvider.MOCK
    assert client.__class__.__name__ == "MockModelClient"
