from __future__ import annotations

"""Model client adapters
Wraps mock and openai compatible json generation"""

import json
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from packages.memory_core.utils import extract_entities, unique_topics


TEMPORAL_TOPIC_TOKENS = {
    "after",
    "around",
    "before",
    "day",
    "days",
    "earlier",
    "evening",
    "hour",
    "hours",
    "later",
    "latest",
    "minute",
    "minutes",
    "mon",
    "monday",
    "month",
    "months",
    "morning",
    "night",
    "pm",
    "am",
    "recent",
    "recently",
    "same",
    "today",
    "tomorrow",
    "tonight",
    "week",
    "weeks",
    "yesterday",
    "jan",
    "january",
    "feb",
    "february",
    "mar",
    "march",
    "apr",
    "april",
    "may",
    "jun",
    "june",
    "jul",
    "july",
    "aug",
    "august",
    "sep",
    "sept",
    "september",
    "oct",
    "october",
    "nov",
    "november",
    "dec",
    "december",
}

EXACT_TEMPORAL_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2})?\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}(?:,?\s+\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)?\b"),
    re.compile(r"\b\d{1,2}:\d{2}\s*[AaPp][Mm]\b"),
)


def _verification_subject_payload(user_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if "summary" in user_payload:
        return "summary", dict(user_payload["summary"])
    if "answer" in user_payload:
        return "answer", dict(user_payload["answer"])
    return "answer", {}


def _is_temporal_topic_token(token: str) -> bool:
    lowered = token.lower()
    if lowered in TEMPORAL_TOPIC_TOKENS:
        return True
    if lowered.isdigit():
        return True
    return bool(re.fullmatch(r"\d{1,2}(am|pm)", lowered))


def _extract_exact_temporal_phrases(text: str) -> list[str]:
    matches: list[str] = []
    for pattern in EXACT_TEMPORAL_PATTERNS:
        for match in pattern.finditer(text):
            phrase = match.group(0).strip()
            if phrase not in matches:
                matches.append(phrase)
    return matches


def _find_temporal_unsupported_claims(summary_text: str, support_entries: list[dict[str, Any]]) -> list[str]:
    support_texts = [str(item.get("text", "")) for item in support_entries]
    explicit_support_temporal_phrases = {
        phrase.lower()
        for text in support_texts
        for phrase in _extract_exact_temporal_phrases(text)
    }
    unsupported: list[str] = []
    for phrase in _extract_exact_temporal_phrases(summary_text):
        if phrase.lower() not in explicit_support_temporal_phrases:
            unsupported.append(
                f"The summary includes an exact timestamp '{phrase}' that is not explicit in the supporting memory text."
            )
    return unsupported


def _mock_answer_from_context(query: str, retrieved_nodes: list[dict[str, Any]], packed_context: str) -> dict[str, Any]:
    query_lower = query.lower()
    unique_nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in retrieved_nodes:
        node_id = str(item.get("node_id", ""))
        if not node_id or node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        unique_nodes.append(item)

    if not unique_nodes:
        return {
            "text": "I don't have enough retrieved evidence to answer that yet.",
            "citations": [],
            "confidence": 0.0,
        }

    query_entities = [entity for entity in extract_entities(query) if entity]
    if any(token in query_lower for token in [" vs ", "versus", "differently from", "compare"]) and len(query_entities) >= 2:
        comparison_parts: list[str] = []
        comparison_citations: list[str] = []
        for entity in query_entities[:3]:
            match = next(
                (
                    node
                    for node in unique_nodes
                    if entity.lower() in node.get("text", "").lower()
                    or entity.lower() in {item.lower() for item in node.get("entities", [])}
                ),
                None,
            )
            if match is None:
                continue
            comparison_parts.append(f"{entity}: {match.get('text', '').strip().rstrip('.')}.")
            comparison_citations.append(str(match.get("node_id", "")))
        if len(comparison_parts) >= 2:
            return {
                "text": " ".join(comparison_parts),
                "citations": [citation for citation in comparison_citations if citation],
                "confidence": 0.68,
            }

    snippets = [node.get("text", "").strip().rstrip(".") for node in unique_nodes[:2] if node.get("text")]
    if not snippets and packed_context.strip():
        snippets = [line.strip() for line in packed_context.splitlines()[2:4] if line.strip()]
    answer_text = "Based on the retrieved context: " + ". ".join(snippets)
    if not snippets:
        answer_text = "I don't have enough retrieved evidence to answer that yet."
    return {
        "text": answer_text.strip(),
        "citations": [str(node.get("node_id", "")) for node in unique_nodes[:2] if node.get("node_id")],
        "confidence": 0.62 if snippets else 0.0,
    }


class ModelClient(ABC):
    """Abstract interface for structured model calls
    Implementations must return JSON payloads matching component schemas"""

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
    """Deterministic local model client
    Used for tests smoke checks and offline runs without external API calls"""

    def generate_json(
        self,
        *,
        component: str,
        model_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Return synthetic payload by component type"""
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
        if component == "answerer":
            return _mock_answer_from_context(
                str(user_payload.get("query", "")),
                list(user_payload.get("retrieved_nodes", [])),
                str(user_payload.get("packed_context", "")),
            )
        subject_label, subject_payload = _verification_subject_payload(user_payload)
        summary_text = str(subject_payload.get("text", ""))
        support_entries = user_payload["supports"]
        support_text = " ".join(item["text"] for item in support_entries)
        unsupported_claims: list[str] = []
        contradictions: list[str] = []
        temporal_unsupported_claims = _find_temporal_unsupported_claims(summary_text, support_entries)
        for token in unique_topics(summary_text, limit=15):
            if _is_temporal_topic_token(token):
                continue
            if token not in set(unique_topics(support_text, limit=40)):
                unsupported_claims.append(token)
        unsupported_claims.extend(temporal_unsupported_claims)
        if " not " in f" {summary_text.lower()} " and " not " not in f" {support_text.lower()} ":
            contradictions.append("negation mismatch")
        quality_status = "verified"
        if contradictions:
            quality_status = "contradicted"
        elif temporal_unsupported_claims or len(unsupported_claims) > 4:
            quality_status = "unsupported"
        return {
            "quality_status": quality_status,
            "unsupported_claims": [
                claim if claim.startswith("The ") else f"The {subject_label} includes unsupported content: {claim}"
                for claim in unsupported_claims
            ],
            "contradictions": contradictions,
            "omissions": [],
            "scores": {
                "unsupported_ratio": len(unsupported_claims) / max(len(unique_topics(summary_text, limit=15)), 1),
                "support_overlap": max(0.0, 1.0 - len(unsupported_claims) / max(len(unique_topics(summary_text, limit=15)), 1)),
                "contradiction_score": 1.0 if contradictions else 0.0,
            },
        }


class OpenAICompatibleClient(ModelClient):
    """Responses API client for openai compatible endpoints
    Handles retries transient failures and strict JSON schema responses"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    def _retry_sleep_seconds(self, attempt_index: int) -> float:
        # backoff plus small jitter to smooth retries
        return self.retry_backoff_seconds * (2 ** max(0, attempt_index - 1)) + random.uniform(0.0, 0.25)

    def generate_json(
        self,
        *,
        component: str,
        model_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Call responses API and parse strict json content"""
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
        endpoint = f"{self.base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response: httpx.Response | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                response = httpx.post(
                    endpoint,
                    headers=headers,
                    json=request_body,
                    timeout=self.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt > self.max_retries:
                    raise RuntimeError(
                        f"Responses API request failed after {attempt} attempts with transport timeout/error: {exc}"
                    ) from exc
                time.sleep(self._retry_sleep_seconds(attempt))
                continue

            # retry transient server and rate limit failures
            if response.status_code in {408, 409, 429} or response.status_code >= 500:
                if attempt > self.max_retries:
                    raise RuntimeError(
                        f"Responses API request failed after {attempt} attempts with status {response.status_code}: {response.text}"
                    )
                time.sleep(self._retry_sleep_seconds(attempt))
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Responses API request failed with {response.status_code}: {response.text}"
                ) from exc
            break

        if response is None:
            raise RuntimeError("Responses API request failed before receiving any response.")

        payload = response.json()
        content = payload.get("output_text")
        if not content:
            content = self._extract_response_text(payload)
        return json.loads(content)

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        """Extract text from message style output array"""
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    return content["text"]
        raise RuntimeError("Responses API returned no parseable text output.")

    def _schema_for_component(self, component: str) -> dict[str, Any]:
        """Return strict json schema for component response"""
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
        if component == "answerer":
            return {
                "name": "answer_result",
                "description": "Grounded answer generated only from retrieved memory context.",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string"},
                        "citations": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                    },
                    "required": ["text", "citations", "confidence"],
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
