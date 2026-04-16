from __future__ import annotations

"""Typed contracts for retrieval pipeline steps
Defines request outcome and step protocols"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from packages.schemas.models import MemoryNode, QueryMode, RetrievalTraceEntry


@dataclass
class CandidateScore:
    node: MemoryNode
    score: float
    relevance: float
    recency: float


@dataclass(frozen=True)
class QueryRoutingDecision:
    strategy: str
    reason: str
    feature_scores: dict[str, float]
    fired_rules: list[str]
    hierarchical_score: float
    branch_limit_override: int
    enable_coverage_expansion: bool
    enable_revision_enrichment: bool


class CoveragePlanLike(Protocol):
    min_leaf_count: int
    required_facets: tuple[str, ...]
    communication_facets: tuple[str, ...]
    communication_min_hits: int
    enforce_entity_thread: bool
    requires_multi_leaf: bool
    has_required_facets: bool


@dataclass(frozen=True)
class RetrievalRouteContext:
    routing: QueryRoutingDecision
    temporal_cue: float
    ambiguity_cue: float
    query_entities: list[str]
    feature_active_min: float
    expansion_target: int
    supplemental_weights: dict[str, float]
    composition_query: bool
    negation_sensitive_query: bool
    conflict_query: bool
    coverage_query: bool
    coverage_plan: CoveragePlanLike
    routing_attribution: dict[str, object]


@dataclass(frozen=True)
class LeafFirstOutcome:
    handled: bool
    selected: list[CandidateScore]
    max_depth: int
    trace_entries: list[RetrievalTraceEntry]
    detail_query: bool
    revision_query: bool
    cross_branch_revision_query: bool
    ranked_leaf_candidates: list[CandidateScore]
    low_confidence: bool
    target_person_strategy_resolver: bool
    disambiguation_pressure: bool
    revision_needs_expansion: bool
    routing_attribution_updates: dict[str, object]


@dataclass(frozen=True)
class LeafFirstEvaluationContext:
    detail_query: bool
    revision_query: bool
    cross_branch_revision_query: bool
    ranked_leaf_candidates: list[CandidateScore]
    top_leaf_probe: list[CandidateScore]
    low_confidence: bool


@dataclass(frozen=True)
class LeafFirstSignals:
    target_person_strategy_resolver: bool
    disambiguation_pressure: bool
    revision_leaf_first_query: bool
    revision_needs_expansion: bool
    routing_updates: dict[str, object]


@dataclass(frozen=True)
class BranchRankingOutcome:
    picked: list[CandidateScore]
    consumed: int
    max_depth: int
    trace_entries: list[RetrievalTraceEntry]


@dataclass(frozen=True)
class SupplementalSelectionOutcome:
    picked: list[CandidateScore]
    trace_entries: list[RetrievalTraceEntry]


@dataclass(frozen=True)
class RetrievalPipelineRequest:
    agent_id: str
    query: str
    query_time: datetime
    mode: QueryMode
    token_budget: int
    branch_limit: int


@dataclass(frozen=True)
class RouteQueryInput:
    agent_id: str
    query: str
    mode: QueryMode
    branch_limit: int


@dataclass(frozen=True)
class LeafFirstInput:
    agent_id: str
    query: str
    query_time: datetime
    mode: QueryMode
    token_budget: int
    route_context: RetrievalRouteContext


@dataclass(frozen=True)
class BranchRankingInput:
    agent_id: str
    query: str
    query_time: datetime
    mode: QueryMode
    token_budget: int
    branch_limit: int
    route_context: RetrievalRouteContext
    leaf_outcome: LeafFirstOutcome


@dataclass(frozen=True)
class SupplementalSelectionInput:
    query: str
    query_time: datetime
    mode: QueryMode
    token_budget: int
    route_context: RetrievalRouteContext
    leaf_outcome: LeafFirstOutcome
    picked: list[CandidateScore]
    consumed: int
    trace_entries: list[RetrievalTraceEntry]


@dataclass(frozen=True)
class BuildTraceInput:
    agent_id: str
    query: str
    query_time: datetime
    token_budget: int
    branch_limit: int
    detail_query: bool
    picked: list[CandidateScore]
    max_depth: int
    trace_entries: list[RetrievalTraceEntry]
    routing_attribution: dict[str, object]


@dataclass(frozen=True)
class RetrievalPipelineResult:
    selected: list[CandidateScore]
    max_depth: int
    trace_entries: list[RetrievalTraceEntry]
    routing_attribution: dict[str, object]

    def as_tuple(self) -> tuple[list[CandidateScore], int, list[RetrievalTraceEntry], dict[str, object]]:
        return self.selected, self.max_depth, self.trace_entries, self.routing_attribution


class RouteQueryStep(Protocol):
    def __call__(self, input_data: RouteQueryInput) -> RetrievalRouteContext: ...


class AttemptLeafFirstStep(Protocol):
    def __call__(self, input_data: LeafFirstInput) -> LeafFirstOutcome: ...


class RankSummariesAndBranchesStep(Protocol):
    def __call__(self, input_data: BranchRankingInput) -> BranchRankingOutcome: ...


class ApplySupplementalSelectionStep(Protocol):
    def __call__(self, input_data: SupplementalSelectionInput) -> SupplementalSelectionOutcome: ...


class BuildTraceAndDiagnosticsStep(Protocol):
    def __call__(self, input_data: BuildTraceInput) -> RetrievalPipelineResult: ...


@dataclass(frozen=True)
class RetrievalPipelineInterfaces:
    route_query: RouteQueryStep
    attempt_leaf_first: AttemptLeafFirstStep
    rank_summaries_and_branches: RankSummariesAndBranchesStep
    apply_supplemental_selection: ApplySupplementalSelectionStep
    build_trace_and_diagnostics: BuildTraceAndDiagnosticsStep
