from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from packages.memory_core.utils import extract_entities, unique_topics


class ModelClient(ABC):
    @abstractmethod
    def generate_json(
        self,
        *,
        component: str,
        model_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class MockModelClient(ModelClient):
    def generate_json(
        self,
        *,
        component: str,
        model_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        del model_name, system_prompt
        if component == "summarizer":
            child_nodes = user_payload["child_nodes"]
            texts = [item["text"].strip().rstrip(".") for item in child_nodes]
            summary = " | ".join(texts[:3])
            if len(texts) > 3:
                summary += f" | plus {len(texts) - 3} related events"
            return {
                "text": summary[:600],
                "entities": extract_entities(summary),
                "topics": unique_topics(summary),
                "confidence": 0.72,
                "citations": [item["node_id"] for item in child_nodes],
            }
        summary_text = user_payload["summary"]["text"]
        support_text = " ".join(item["text"] for item in user_payload["supports"])
        unsupported_claims: list[str] = []
        contradictions: list[str] = []
        for token in unique_topics(summary_text, limit=15):
            if token not in set(unique_topics(support_text, limit=40)):
                unsupported_claims.append(token)
        if " not " in f" {summary_text.lower()} " and " not " not in f" {support_text.lower()} ":
            contradictions.append("negation mismatch")
        quality_status = "verified"
        if contradictions:
            quality_status = "contradicted"
        elif len(unsupported_claims) > 4:
            quality_status = "unsupported"
        return {
            "quality_status": quality_status,
            "unsupported_claims": unsupported_claims,
            "contradictions": contradictions,
            "omissions": [],
            "scores": {
                "unsupported_ratio": len(unsupported_claims) / max(len(unique_topics(summary_text, limit=15)), 1),
                "support_overlap": max(0.0, 1.0 - len(unsupported_claims) / max(len(unique_topics(summary_text, limit=15)), 1)),
                "contradiction_score": 1.0 if contradictions else 0.0,
            },
        }


class OpenAICompatibleClient(ModelClient):
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate_json(
        self,
        *,
        component: str,
        model_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("PROJECT_MODEL_API_KEY is required for openai-compatible provider.")
        schema = self._schema_for_component(component)
        request_body = {
            "model": model_name,
            "instructions": system_prompt,
            "input": json.dumps({"component": component, "payload": user_payload}),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema["name"],
                    "description": schema["description"],
                    "schema": schema["schema"],
                    "strict": True,
                }
            },
        }
        response = httpx.post(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Responses API request failed with {response.status_code}: {response.text}"
            ) from exc
        payload = response.json()
        content = payload.get("output_text")
        if not content:
            content = self._extract_response_text(payload)
        return json.loads(content)

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    return content["text"]
        raise RuntimeError("Responses API returned no parseable text output.")

    def _schema_for_component(self, component: str) -> dict[str, Any]:
        if component == "summarizer":
            return {
                "name": "summary_result",
                "description": "Structured summary response for a memory cluster.",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string"},
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "topics": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                        "citations": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "entities", "topics", "confidence", "citations"],
                },
            }
        return {
            "name": "verification_result",
            "description": "Structured verification result for a summary and its supporting memories.",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "quality_status": {"type": "string", "enum": ["pending", "verified", "unsupported", "contradicted"]},
                    "unsupported_claims": {"type": "array", "items": {"type": "string"}},
                    "contradictions": {"type": "array", "items": {"type": "string"}},
                    "omissions": {"type": "array", "items": {"type": "string"}},
                    "scores": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "unsupported_ratio": {"type": "number"},
                            "support_overlap": {"type": "number"},
                            "contradiction_score": {"type": "number"},
                        },
                        "required": ["unsupported_ratio", "support_overlap", "contradiction_score"],
                    },
                },
                "required": ["quality_status", "unsupported_claims", "contradictions", "omissions", "scores"],
            },
        }
