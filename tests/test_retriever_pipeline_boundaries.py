from __future__ import annotations

"""Test module overview for test retriever pipeline boundaries
Covers behavior and regression checks"""

from datetime import datetime, timedelta

from packages.memory_core.retrieval.policies import CoveragePlan
from packages.memory_core.retrieval.pipeline_types import (
    BranchRankingInput,
    BranchRankingOutcome,
    BuildTraceInput,
    CandidateScore,
    LeafFirstInput,
    LeafFirstOutcome,
    QueryRoutingDecision,
    RetrievalPipelineInterfaces,
    RetrievalPipelineRequest,
    RetrievalPipelineResult,
    RetrievalRouteContext,
    RouteQueryInput,
    SupplementalSelectionInput,
    SupplementalSelectionOutcome,
)
from packages.schemas.models import MemoryLevel, QueryMode, RetrievalTraceEntry


def _make_candidate(memory_service, agent_id: str, text: str, ts: datetime, *, score: float) -> CandidateScore:
    node = memory_service.agent_loop.observe(agent_id, text, ts, 0.8)
    return CandidateScore(node=node, score=score, relevance=score, recency=score)


def _make_route_context(*, strategy: str, attribution: dict[str, object] | None = None) -> RetrievalRouteContext:
    routing = QueryRoutingDecision(
        strategy=strategy,
        reason=f"forced-{strategy}",
        feature_scores={"hierarchical_score": 0.5},
        fired_rules=[],
        hierarchical_score=0.5,
        branch_limit_override=2,
        enable_coverage_expansion=False,
        enable_revision_enrichment=False,
    )
    return RetrievalRouteContext(
        routing=routing,
        temporal_cue=0.0,
        ambiguity_cue=0.0,
        query_entities=[],
        feature_active_min=0.3,
        expansion_target=2,
        supplemental_weights={},
        composition_query=False,
        negation_sensitive_query=False,
        conflict_query=False,
        coverage_query=False,
        coverage_plan=CoveragePlan(
            min_leaf_count=1,
            required_facets=(),
            communication_facets=(),
            communication_min_hits=0,
            enforce_entity_thread=False,
        ),
        routing_attribution=attribution or {"routing_strategy": strategy},
    )


def _trace_for(item: CandidateScore, *, selected_as: str) -> RetrievalTraceEntry:
    return RetrievalTraceEntry(
        node_id=item.node.node_id,
        level=item.node.level,
        node_type=item.node.node_type,
        score=item.score,
        relevance_score=item.relevance,
        recency_score=item.recency,
        importance_score=item.node.importance_score,
        branch_root_id=None,
        selected_as=selected_as,
        selection_reason=f"selected-as-{selected_as}",
    )


def test_retrieve_pipeline_short_circuits_on_flat_top1_route(memory_service, monkeypatch) -> None:
    retriever = memory_service.hierarchical_retriever
    base = datetime(2025, 1, 1, 9, 0, 0)
    candidate = _make_candidate(memory_service, "agent-pipeline-flat", "flat route leaf", base, score=0.91)
    ctx = _make_route_context(strategy="flat_top1")

    monkeypatch.setattr(retriever, "route_query", lambda **kwargs: ctx)
    monkeypatch.setattr(retriever.flat_retriever, "retrieve", lambda *args, **kwargs: [candidate])

    def _should_not_run(**kwargs):
        raise AssertionError("pipeline should have returned before this phase")

    monkeypatch.setattr(retriever, "attempt_leaf_first", _should_not_run)
    monkeypatch.setattr(retriever, "rank_summaries_and_branches", _should_not_run)
    monkeypatch.setattr(retriever, "apply_supplemental_selection", _should_not_run)
    monkeypatch.setattr(retriever, "build_trace_and_diagnostics", _should_not_run)

    selected, depth, trace_entries, routing_attribution = retriever.retrieve(
        agent_id="agent-pipeline-flat",
        query="what did I commit to",
        query_time=base + timedelta(hours=1),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=2,
    )

    assert selected == [candidate]
    assert depth == 1
    assert len(trace_entries) == 1
    assert trace_entries[0].selected_as == "query_router_flat"
    assert routing_attribution["routing_strategy"] == "flat_top1"


def test_retrieve_pipeline_short_circuits_on_handled_leaf_outcome(memory_service, monkeypatch) -> None:
    retriever = memory_service.hierarchical_retriever
    base = datetime(2025, 1, 1, 9, 0, 0)
    candidate = _make_candidate(memory_service, "agent-pipeline-leaf", "leaf handled route", base, score=0.88)
    trace_entry = _trace_for(candidate, selected_as="query_router_flat")

    route_context = _make_route_context(strategy="hierarchical", attribution={"routing_strategy": "hierarchical"})
    leaf_outcome = LeafFirstOutcome(
        handled=True,
        selected=[candidate],
        max_depth=1,
        trace_entries=[trace_entry],
        detail_query=False,
        revision_query=False,
        cross_branch_revision_query=False,
        ranked_leaf_candidates=[candidate],
        low_confidence=False,
        target_person_strategy_resolver=False,
        disambiguation_pressure=False,
        revision_needs_expansion=False,
        routing_attribution_updates={"disambiguation_pressure": 0.0},
    )

    monkeypatch.setattr(retriever, "route_query", lambda **kwargs: route_context)
    monkeypatch.setattr(retriever, "attempt_leaf_first", lambda **kwargs: leaf_outcome)

    def _should_not_run(**kwargs):
        raise AssertionError("downstream phases should not run when leaf outcome is handled")

    monkeypatch.setattr(retriever, "rank_summaries_and_branches", _should_not_run)
    monkeypatch.setattr(retriever, "apply_supplemental_selection", _should_not_run)
    monkeypatch.setattr(retriever, "build_trace_and_diagnostics", _should_not_run)

    selected, depth, trace_entries, routing_attribution = retriever.retrieve(
        agent_id="agent-pipeline-leaf",
        query="what should I do",
        query_time=base + timedelta(hours=1),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=2,
    )

    assert selected == [candidate]
    assert depth == 1
    assert trace_entries == [trace_entry]
    assert routing_attribution["routing_strategy"] == "hierarchical"
    assert routing_attribution["disambiguation_pressure"] == 0.0


def test_retrieve_pipeline_passes_step_outputs_to_next_phase(memory_service, monkeypatch) -> None:
    retriever = memory_service.hierarchical_retriever
    base = datetime(2025, 1, 1, 9, 0, 0)

    route_context = _make_route_context(strategy="hierarchical", attribution={"routing_strategy": "hierarchical"})
    leaf_seed = _make_candidate(memory_service, "agent-pipeline-full", "leaf seed", base, score=0.6)
    ranked_seed = _make_candidate(memory_service, "agent-pipeline-full", "ranked seed", base + timedelta(minutes=1), score=0.7)
    final_candidate = _make_candidate(memory_service, "agent-pipeline-full", "final picked", base + timedelta(minutes=2), score=0.95)

    leaf_outcome = LeafFirstOutcome(
        handled=False,
        selected=[],
        max_depth=0,
        trace_entries=[],
        detail_query=True,
        revision_query=False,
        cross_branch_revision_query=False,
        ranked_leaf_candidates=[leaf_seed],
        low_confidence=False,
        target_person_strategy_resolver=False,
        disambiguation_pressure=False,
        revision_needs_expansion=False,
        routing_attribution_updates={"leaf_phase": "ran"},
    )
    branch_trace = [_trace_for(ranked_seed, selected_as="summary")]
    supplemental_trace = [_trace_for(final_candidate, selected_as="supporting_leaf")]

    call_order: list[str] = []

    def _route(**kwargs):
        call_order.append("route")
        return route_context

    def _leaf(**kwargs):
        call_order.append("leaf")
        assert kwargs["route_context"] is route_context
        return leaf_outcome

    def _rank(**kwargs):
        call_order.append("rank")
        assert kwargs["route_context"] is route_context
        assert kwargs["leaf_outcome"] is leaf_outcome
        return BranchRankingOutcome(
            picked=[ranked_seed],
            consumed=11,
            max_depth=2,
            trace_entries=branch_trace,
        )

    def _supplement(**kwargs):
        call_order.append("supplement")
        assert kwargs["route_context"] is route_context
        assert kwargs["leaf_outcome"] is leaf_outcome
        assert kwargs["picked"] == [ranked_seed]
        assert kwargs["consumed"] == 11
        assert kwargs["trace_entries"] == branch_trace
        return SupplementalSelectionOutcome(
            picked=[final_candidate],
            trace_entries=supplemental_trace,
        )

    expected = ([final_candidate], 2, supplemental_trace, {"routing_strategy": "hierarchical", "leaf_phase": "ran"})

    def _build(**kwargs):
        call_order.append("build")
        assert kwargs["detail_query"] is True
        assert kwargs["picked"] == [final_candidate]
        assert kwargs["max_depth"] == 2
        assert kwargs["trace_entries"] == supplemental_trace
        assert kwargs["routing_attribution"] == {"routing_strategy": "hierarchical", "leaf_phase": "ran"}
        return expected

    monkeypatch.setattr(retriever, "route_query", _route)
    monkeypatch.setattr(retriever, "attempt_leaf_first", _leaf)
    monkeypatch.setattr(retriever, "rank_summaries_and_branches", _rank)
    monkeypatch.setattr(retriever, "apply_supplemental_selection", _supplement)
    monkeypatch.setattr(retriever, "build_trace_and_diagnostics", _build)

    result = retriever.retrieve(
        agent_id="agent-pipeline-full",
        query="how should I communicate",
        query_time=base + timedelta(hours=1),
        mode=QueryMode.BALANCED,
        token_budget=120,
        branch_limit=3,
    )

    assert result == expected
    assert call_order == ["route", "leaf", "rank", "supplement", "build"]


def test_characterization_build_trace_fallback_uses_detail_query_cap(memory_service, monkeypatch) -> None:
    retriever = memory_service.hierarchical_retriever
    base = datetime(2025, 1, 1, 9, 0, 0)
    c1 = _make_candidate(memory_service, "agent-char-fallback", "fallback leaf one", base, score=0.4)
    c2 = _make_candidate(memory_service, "agent-char-fallback", "fallback leaf two", base + timedelta(minutes=1), score=0.3)

    observed_limits: list[int] = []

    def _flat(agent_id, query, query_time, token_budget, limit):
        observed_limits.append(limit)
        return [c1, c2]

    monkeypatch.setattr(retriever.flat_retriever, "retrieve", _flat)

    selected, depth, trace_entries, attribution = retriever.build_trace_and_diagnostics(
        agent_id="agent-char-fallback",
        query="what changed",
        query_time=base + timedelta(hours=1),
        token_budget=100,
        branch_limit=5,
        detail_query=True,
        picked=[],
        max_depth=0,
        trace_entries=[],
        routing_attribution={"routing_strategy": "hierarchical"},
    )

    assert observed_limits == [2]
    assert selected == [c1, c2]
    assert depth == 1
    assert [entry.selected_as for entry in trace_entries] == ["flat_fallback", "flat_fallback"]
    assert attribution["routing_strategy"] == "hierarchical"


def test_characterization_build_trace_sorts_final_picks_by_score(memory_service) -> None:
    retriever = memory_service.hierarchical_retriever
    base = datetime(2025, 1, 1, 9, 0, 0)
    low = _make_candidate(memory_service, "agent-char-sort", "low score", base, score=0.21)
    high = _make_candidate(memory_service, "agent-char-sort", "high score", base + timedelta(minutes=1), score=0.97)

    selected, depth, trace_entries, attribution = retriever.build_trace_and_diagnostics(
        agent_id="agent-char-sort",
        query="summarize",
        query_time=base + timedelta(hours=1),
        token_budget=100,
        branch_limit=3,
        detail_query=False,
        picked=[low, high],
        max_depth=2,
        trace_entries=[_trace_for(low, selected_as="summary"), _trace_for(high, selected_as="supporting_leaf")],
        routing_attribution={"routing_strategy": "hierarchical"},
    )

    assert [item.node.node_id for item in selected] == [high.node.node_id, low.node.node_id]
    assert depth == 2
    assert len(trace_entries) == 2
    assert attribution["routing_strategy"] == "hierarchical"
    assert all(item.node.level in {MemoryLevel.L0, MemoryLevel.L1} for item in selected)


def test_retrieve_with_pipeline_interfaces_supports_typed_step_injection(memory_service) -> None:
    retriever = memory_service.hierarchical_retriever
    base = datetime(2025, 1, 1, 9, 0, 0)
    final_candidate = _make_candidate(memory_service, "agent-pipeline-typed", "typed pipeline final", base, score=0.93)
    trace_entry = _trace_for(final_candidate, selected_as="supporting_leaf")

    route_context = _make_route_context(strategy="hierarchical", attribution={"routing_strategy": "hierarchical"})
    leaf_outcome = LeafFirstOutcome(
        handled=False,
        selected=[],
        max_depth=0,
        trace_entries=[],
        detail_query=True,
        revision_query=False,
        cross_branch_revision_query=False,
        ranked_leaf_candidates=[final_candidate],
        low_confidence=False,
        target_person_strategy_resolver=False,
        disambiguation_pressure=False,
        revision_needs_expansion=False,
        routing_attribution_updates={"typed": True},
    )

    def _route(input_data: RouteQueryInput) -> RetrievalRouteContext:
        assert input_data.agent_id == "agent-pipeline-typed"
        assert input_data.mode == QueryMode.BALANCED
        return route_context

    def _leaf(input_data: LeafFirstInput) -> LeafFirstOutcome:
        assert input_data.route_context is route_context
        return leaf_outcome

    def _rank(input_data: BranchRankingInput) -> BranchRankingOutcome:
        assert input_data.leaf_outcome is leaf_outcome
        return BranchRankingOutcome(
            picked=[final_candidate],
            consumed=final_candidate.node.token_count,
            max_depth=2,
            trace_entries=[trace_entry],
        )

    def _supplement(input_data: SupplementalSelectionInput) -> SupplementalSelectionOutcome:
        assert input_data.picked == [final_candidate]
        return SupplementalSelectionOutcome(
            picked=[final_candidate],
            trace_entries=[trace_entry],
        )

    def _build(input_data: BuildTraceInput) -> RetrievalPipelineResult:
        assert input_data.detail_query is True
        assert input_data.max_depth == 2
        assert input_data.routing_attribution == {"routing_strategy": "hierarchical", "typed": True}
        return RetrievalPipelineResult(
            selected=input_data.picked,
            max_depth=input_data.max_depth,
            trace_entries=input_data.trace_entries,
            routing_attribution=input_data.routing_attribution,
        )

    interfaces = RetrievalPipelineInterfaces(
        route_query=_route,
        attempt_leaf_first=_leaf,
        rank_summaries_and_branches=_rank,
        apply_supplemental_selection=_supplement,
        build_trace_and_diagnostics=_build,
    )
    result = retriever.retrieve_with_pipeline_interfaces(
        request=RetrievalPipelineRequest(
            agent_id="agent-pipeline-typed",
            query="how should I proceed",
            query_time=base + timedelta(hours=1),
            mode=QueryMode.BALANCED,
            token_budget=120,
            branch_limit=3,
        ),
        interfaces=interfaces,
    )

    assert result.selected == [final_candidate]
    assert result.max_depth == 2
    assert result.trace_entries == [trace_entry]
    assert result.routing_attribution["typed"] is True
