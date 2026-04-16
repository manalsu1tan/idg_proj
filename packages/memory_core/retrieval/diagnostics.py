from __future__ import annotations

"""Retrieval diagnostics helpers
Builds trace entries and aggregate diagnostics"""

import statistics
from dataclasses import dataclass
from typing import Protocol

from packages.memory_core.utils import token_count
from packages.schemas.models import MemoryLevel, MemoryNode, RetrievalDiagnostics, RetrievalTraceEntry


@dataclass(frozen=True)
class RoutingDiagnosticsAttribution:
    routing_strategy: str | None
    query_feature_scores: dict[str, float]
    fired_rules: list[str]


class SupportsCandidateScore(Protocol):
    node: MemoryNode
    score: float
    relevance: float
    recency: float


def extract_routing_diagnostics_attribution(
    routing_attribution: dict[str, object] | None,
) -> RoutingDiagnosticsAttribution:
    if not routing_attribution:
        return RoutingDiagnosticsAttribution(
            routing_strategy=None,
            query_feature_scores={},
            fired_rules=[],
        )
    query_feature_scores_raw = routing_attribution.get("query_feature_scores", {})
    fired_rules_raw = routing_attribution.get("fired_rules", [])
    return RoutingDiagnosticsAttribution(
        routing_strategy=str(routing_attribution.get("routing_strategy"))
        if routing_attribution.get("routing_strategy") is not None
        else None,
        query_feature_scores={
            str(key): float(value)
            for key, value in dict(query_feature_scores_raw).items()
            if isinstance(value, (int, float))
        }
        if isinstance(query_feature_scores_raw, dict)
        else {},
        fired_rules=[str(item) for item in fired_rules_raw]
        if isinstance(fired_rules_raw, list)
        else [],
    )


def make_retrieval_trace_entry(
    candidate: SupportsCandidateScore,
    *,
    selected_as: str,
    selection_reason: str,
    branch_root_id: str | None = None,
) -> RetrievalTraceEntry:
    return RetrievalTraceEntry(
        node_id=candidate.node.node_id,
        level=candidate.node.level,
        node_type=candidate.node.node_type,
        score=candidate.score,
        relevance_score=candidate.relevance,
        recency_score=candidate.recency,
        importance_score=candidate.node.importance_score,
        branch_root_id=branch_root_id,
        selected_as=selected_as,
        selection_reason=selection_reason,
    )


def build_retrieval_diagnostics(
    candidates: list[SupportsCandidateScore],
    trace_entries: list[RetrievalTraceEntry],
    packed_context: str,
    routing_attribution: dict[str, object] | None = None,
) -> RetrievalDiagnostics:
    routing_diag = extract_routing_diagnostics_attribution(routing_attribution)
    retrieved_token_count = sum(item.node.token_count for item in candidates)
    summary_node_count = sum(1 for item in candidates if item.node.level != MemoryLevel.L0)
    supporting_leaf_count = sum(1 for entry in trace_entries if entry.selected_as == "supporting_leaf")
    branch_count = len({entry.branch_root_id for entry in trace_entries if entry.branch_root_id})
    scores = [item.score for item in candidates]
    return RetrievalDiagnostics(
        retrieved_node_count=len(candidates),
        summary_node_count=summary_node_count,
        leaf_node_count=sum(1 for item in candidates if item.node.level == MemoryLevel.L0),
        supporting_leaf_count=supporting_leaf_count,
        retrieved_token_count=retrieved_token_count,
        packed_token_count=token_count(packed_context),
        branch_count=branch_count,
        avg_score=statistics.fmean(scores) if scores else 0.0,
        max_score=max(scores, default=0.0),
        fallback_used=any(entry.selected_as == "flat_fallback" for entry in trace_entries),
        routing_strategy=routing_diag.routing_strategy,
        query_feature_scores=dict(routing_diag.query_feature_scores),
        fired_rules=list(routing_diag.fired_rules),
    )

