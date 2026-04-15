from __future__ import annotations

import sys
import uuid
from datetime import datetime

from packages.memory_core.model_clients import ModelClient, MockModelClient, OpenAICompatibleClient
from packages.memory_core.prompts import load_prompt
from packages.memory_core.settings import Settings
from packages.memory_core.utils import extract_entities, token_count, truncate_to_token_count, unique_topics
from packages.schemas.models import (
    MemoryNode,
    ModelProvider,
    ModelTrace,
    QualityStatus,
    SummaryResult,
    VerificationResult,
)


def build_model_client(settings: Settings) -> tuple[ModelClient, ModelProvider]:
    if settings.model_provider == ModelProvider.OPENAI_COMPATIBLE.value:
        if not settings.model_api_key:
            print(
                "PROJECT_MODEL_API_KEY is not set; falling back to mock model client.",
                file=sys.stderr,
            )
            return MockModelClient(), ModelProvider.MOCK
        return (
            OpenAICompatibleClient(
                base_url=settings.model_base_url,
                api_key=settings.model_api_key,
                timeout_seconds=settings.model_timeout_seconds,
                max_retries=max(0, settings.model_max_retries),
                retry_backoff_seconds=max(0.0, settings.model_retry_backoff_seconds),
            ),
            ModelProvider.OPENAI_COMPATIBLE,
        )
    return MockModelClient(), ModelProvider.MOCK


class ModelBackedSummarizer:
    def __init__(self, client: ModelClient, provider: ModelProvider, settings: Settings) -> None:
        self.client = client
        self.provider = provider
        self.settings = settings
        self.prompt = load_prompt("summary_prompt.md")

    def generate(self, agent_id: str, child_nodes: list[MemoryNode]) -> tuple[SummaryResult, ModelTrace]:
        summary_token_cap = self._summary_token_cap(child_nodes)
        request_payload = {
            "child_nodes": [
                {
                    "node_id": node.node_id,
                    "text": node.text,
                    "timestamp_start": node.timestamp_start.isoformat(),
                    "timestamp_end": node.timestamp_end.isoformat(),
                    "importance_score": node.importance_score,
                    "entities": node.entities,
                    "topics": node.topics,
                }
                for node in child_nodes
            ]
        }
        response_payload = self.client.generate_json(
            component="summarizer",
            model_name=self.settings.summary_model,
            system_prompt=f"{self.prompt}\nKeep the final summary under {summary_token_cap} tokens.",
            user_payload=request_payload,
        )
        raw_text = response_payload.get("text", "").strip()
        capped_text = truncate_to_token_count(raw_text, summary_token_cap)
        result = SummaryResult(
            text=capped_text,
            entities=response_payload.get("entities", []) or extract_entities(capped_text),
            topics=response_payload.get("topics", []) or unique_topics(capped_text),
            confidence=float(response_payload.get("confidence", 0.0)),
            citations=response_payload.get("citations", []),
            prompt_version=self.settings.prompt_version,
            model_version=self.settings.summary_model,
            raw_response={
                **response_payload,
                "text": capped_text,
                "token_capped": token_count(raw_text) > summary_token_cap,
                "original_text": raw_text,
                "summary_token_cap": summary_token_cap,
            },
        )
        trace = ModelTrace(
            trace_id=str(uuid.uuid4()),
            node_id=None,
            agent_id=agent_id,
            component="summarizer",
            provider=self.provider,
            model_name=self.settings.summary_model,
            prompt_version=self.settings.prompt_version,
            created_at=datetime.utcnow(),
            request_payload=request_payload,
            response_payload=response_payload,
        )
        return result, trace

    def _summary_token_cap(self, child_nodes: list[MemoryNode]) -> int:
        combined = " ".join(node.text for node in child_nodes).lower()
        if any(
            token in combined
            for token in [
                "argument",
                "conflict",
                "tension",
                "trust",
                "feedback",
                "communicat",
                "surprise meeting",
                "relationship",
                "identify as",
                "presenting",
                "energizing",
                "role",
            ]
        ):
            return max(self.settings.summary_max_tokens, self.settings.social_summary_max_tokens)
        return self.settings.summary_max_tokens


class ModelBackedVerifier:
    def __init__(self, client: ModelClient, provider: ModelProvider, settings: Settings) -> None:
        self.client = client
        self.provider = provider
        self.settings = settings
        self.prompt = load_prompt("verifier_prompt.md")

    def verify(self, agent_id: str, summary: MemoryNode, supports: list[MemoryNode]) -> tuple[VerificationResult, ModelTrace]:
        request_payload = {
            "summary": {
                "node_id": summary.node_id,
                "text": summary.text,
                "entities": summary.entities,
                "topics": summary.topics,
            },
            "supports": [
                {
                    "node_id": node.node_id,
                    "text": node.text,
                    "entities": node.entities,
                    "topics": node.topics,
                }
                for node in supports
            ],
        }
        response_payload = self.client.generate_json(
            component="verifier",
            model_name=self.settings.verifier_model,
            system_prompt=self.prompt,
            user_payload=request_payload,
        )
        result = VerificationResult(
            quality_status=QualityStatus(response_payload.get("quality_status", QualityStatus.PENDING.value)),
            unsupported_claims=response_payload.get("unsupported_claims", []),
            contradictions=response_payload.get("contradictions", []),
            omissions=response_payload.get("omissions", []),
            scores=response_payload.get("scores", {}),
            prompt_version=self.settings.prompt_version,
            model_version=self.settings.verifier_model,
            raw_response=response_payload,
        )
        trace = ModelTrace(
            trace_id=str(uuid.uuid4()),
            node_id=summary.node_id,
            agent_id=agent_id,
            component="verifier",
            provider=self.provider,
            model_name=self.settings.verifier_model,
            prompt_version=self.settings.prompt_version,
            created_at=datetime.utcnow(),
            request_payload=request_payload,
            response_payload=response_payload,
        )
        return result, trace
