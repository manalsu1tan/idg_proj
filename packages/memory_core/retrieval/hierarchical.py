from __future__ import annotations

"""Hierarchical retrieval pipeline
Routes queries and selects summary plus leaf evidence"""

import math
import re
import statistics
from datetime import datetime
from typing import Protocol

from packages.memory_core.retrieval.diagnostics import extract_routing_diagnostics_attribution, make_retrieval_trace_entry
from packages.memory_core.retrieval.pipeline_types import (
    BranchRankingInput,
    BranchRankingOutcome,
    BuildTraceInput,
    CandidateScore,
    LeafFirstEvaluationContext,
    LeafFirstInput,
    LeafFirstOutcome,
    LeafFirstSignals,
    QueryRoutingDecision,
    RetrievalPipelineInterfaces,
    RetrievalPipelineRequest,
    RetrievalPipelineResult,
    RetrievalRouteContext,
    RouteQueryInput,
    SupplementalSelectionInput,
    SupplementalSelectionOutcome,
)
from packages.memory_core.retrieval.policies import (
    CoveragePlan,
    QueryFeatureScorer,
    SupplementalScoringPolicy,
    build_coverage_plan,
    dynamic_target_leaf_count,
)
from packages.memory_core.settings import Settings
from packages.memory_core.storage import MemoryStore
from packages.memory_core.utils import extract_entities, normalize_importance, recency_score, relevance_score
from packages.schemas.models import MemoryLevel, MemoryNode, QueryMode, RetrievalTraceEntry

class FlatRetrieverLike(Protocol):
    """Protocol for flat retrieval dependency
    Keeps hierarchical module decoupled from concrete flat retriever"""

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        token_budget: int,
        limit: int = 8,
    ) -> list[CandidateScore]: ...

class HierarchicalRetriever:
    """Hierarchical retrieval orchestrator
    Routes query intent then runs leaf branch supplemental and final assembly phases"""

    ENTITY_ALIAS_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\b([a-z][a-z]+)\s*\((?:aka|a\.k\.a\.|also known as|goes by|called)\s+([a-z][a-z]+)\s*\)"),
        re.compile(r"\b([a-z][a-z]+)\s+(?:aka|a\.k\.a\.|also known as|goes by|called)\s+([a-z][a-z]+)\b"),
    )

    def __init__(self, store: MemoryStore, flat_retriever: FlatRetrieverLike, settings: Settings) -> None:
        self.store = store
        self.flat_retriever = flat_retriever
        self.settings = settings
        self.feature_scorer = QueryFeatureScorer(settings.query_routing_policy)
        self._pipeline_cached_result: tuple[list[CandidateScore], int, list[RetrievalTraceEntry], dict[str, object]] | None = None
        self._pipeline_cached_request: tuple[str, str, datetime, int, int] | None = None

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        branch_limit: int,
    ) -> tuple[list[CandidateScore], int, list[RetrievalTraceEntry], dict[str, object]]:
        """Default retrieval entrypoint for service layer
        Uses typed pipeline interfaces with built in step adapters"""
        result = self.retrieve_with_pipeline_interfaces(
            request=RetrievalPipelineRequest(
                agent_id=agent_id,
                query=query,
                query_time=query_time,
                mode=mode,
                token_budget=token_budget,
                branch_limit=branch_limit,
            ),
            interfaces=RetrievalPipelineInterfaces(
                route_query=self._route_query_step,
                attempt_leaf_first=self._attempt_leaf_first_step,
                rank_summaries_and_branches=self._rank_summaries_and_branches_step,
                apply_supplemental_selection=self._apply_supplemental_selection_step,
                build_trace_and_diagnostics=self._build_trace_and_diagnostics_step,
            ),
        )
        return result.as_tuple()

    def retrieve_with_pipeline_interfaces(
        self,
        *,
        request: RetrievalPipelineRequest,
        interfaces: RetrievalPipelineInterfaces,
    ) -> RetrievalPipelineResult:
        """Runs retrieval pipeline with injectable step handlers
        Enables boundary tests and targeted behavior overrides"""
        # phase 1 route
        route_context = interfaces.route_query(
            RouteQueryInput(
                agent_id=request.agent_id,
                query=request.query,
                mode=request.mode,
                branch_limit=request.branch_limit,
            )
        )

        # fast exit for clear flat_top1 route
        if request.mode == QueryMode.BALANCED and route_context.routing.strategy == "flat_top1":
            routed = self.flat_retriever.retrieve(
                request.agent_id,
                request.query,
                request.query_time,
                request.token_budget,
                limit=1,
            )
            routed_entries = [
                make_retrieval_trace_entry(
                    item,
                    selected_as="query_router_flat",
                    selection_reason=f"Routed by feature scorer to flat top-1. {route_context.routing.reason}",
                )
                for item in routed
            ]
            return RetrievalPipelineResult(
                selected=routed,
                max_depth=1,
                trace_entries=routed_entries,
                routing_attribution=route_context.routing_attribution,
            )

        # phase 2 leaf first decision
        leaf_outcome = interfaces.attempt_leaf_first(
            LeafFirstInput(
                agent_id=request.agent_id,
                query=request.query,
                query_time=request.query_time,
                mode=request.mode,
                token_budget=request.token_budget,
                route_context=route_context,
            )
        )
        routing_attribution = dict(route_context.routing_attribution)
        routing_attribution.update(leaf_outcome.routing_attribution_updates)
        # early return if leaf phase handled fully
        if leaf_outcome.handled:
            return RetrievalPipelineResult(
                selected=leaf_outcome.selected,
                max_depth=leaf_outcome.max_depth,
                trace_entries=leaf_outcome.trace_entries,
                routing_attribution=routing_attribution,
            )

        # phase 3 branch ranking
        branch_ranking = interfaces.rank_summaries_and_branches(
            BranchRankingInput(
                agent_id=request.agent_id,
                query=request.query,
                query_time=request.query_time,
                mode=request.mode,
                token_budget=request.token_budget,
                branch_limit=request.branch_limit,
                route_context=route_context,
                leaf_outcome=leaf_outcome,
            )
        )

        # phase 4 supplemental selection
        supplemental = interfaces.apply_supplemental_selection(
            SupplementalSelectionInput(
                query=request.query,
                query_time=request.query_time,
                mode=request.mode,
                token_budget=request.token_budget,
                route_context=route_context,
                leaf_outcome=leaf_outcome,
                picked=branch_ranking.picked,
                consumed=branch_ranking.consumed,
                trace_entries=branch_ranking.trace_entries,
            )
        )

        # phase 5 final assembly and fallback
        detail_query = leaf_outcome.detail_query
        return interfaces.build_trace_and_diagnostics(
            BuildTraceInput(
                agent_id=request.agent_id,
                query=request.query,
                query_time=request.query_time,
                token_budget=request.token_budget,
                branch_limit=request.branch_limit,
                detail_query=detail_query,
                picked=supplemental.picked,
                max_depth=branch_ranking.max_depth,
                trace_entries=supplemental.trace_entries,
                routing_attribution=routing_attribution,
            )
        )

    def _route_query_step(self, input_data: RouteQueryInput) -> RetrievalRouteContext:
        """Adapter for route_query in typed pipeline mode"""
        return self.route_query(
            agent_id=input_data.agent_id,
            query=input_data.query,
            mode=input_data.mode,
            branch_limit=input_data.branch_limit,
        )

    def _attempt_leaf_first_step(self, input_data: LeafFirstInput) -> LeafFirstOutcome:
        """Adapter for attempt_leaf_first in typed pipeline mode"""
        return self.attempt_leaf_first(
            agent_id=input_data.agent_id,
            query=input_data.query,
            query_time=input_data.query_time,
            mode=input_data.mode,
            token_budget=input_data.token_budget,
            route_context=input_data.route_context,
        )

    def _rank_summaries_and_branches_step(self, input_data: BranchRankingInput) -> BranchRankingOutcome:
        """Adapter for rank_summaries_and_branches in typed pipeline mode"""
        return self.rank_summaries_and_branches(
            agent_id=input_data.agent_id,
            query=input_data.query,
            query_time=input_data.query_time,
            mode=input_data.mode,
            token_budget=input_data.token_budget,
            branch_limit=input_data.branch_limit,
            route_context=input_data.route_context,
            leaf_outcome=input_data.leaf_outcome,
        )

    def _apply_supplemental_selection_step(self, input_data: SupplementalSelectionInput) -> SupplementalSelectionOutcome:
        """Adapter for apply_supplemental_selection in typed pipeline mode"""
        return self.apply_supplemental_selection(
            query=input_data.query,
            query_time=input_data.query_time,
            mode=input_data.mode,
            token_budget=input_data.token_budget,
            route_context=input_data.route_context,
            leaf_outcome=input_data.leaf_outcome,
            picked=input_data.picked,
            consumed=input_data.consumed,
            trace_entries=input_data.trace_entries,
        )

    def _build_trace_and_diagnostics_step(self, input_data: BuildTraceInput) -> RetrievalPipelineResult:
        """Adapter for build_trace_and_diagnostics in typed pipeline mode"""
        selected, max_depth, trace_entries, routing_attribution = self.build_trace_and_diagnostics(
            agent_id=input_data.agent_id,
            query=input_data.query,
            query_time=input_data.query_time,
            token_budget=input_data.token_budget,
            branch_limit=input_data.branch_limit,
            detail_query=input_data.detail_query,
            picked=input_data.picked,
            max_depth=input_data.max_depth,
            trace_entries=input_data.trace_entries,
            routing_attribution=input_data.routing_attribution,
        )
        return RetrievalPipelineResult(
            selected=selected,
            max_depth=max_depth,
            trace_entries=trace_entries,
            routing_attribution=routing_attribution,
        )

    def route_query(
        self,
        *,
        agent_id: str,
        query: str,
        mode: QueryMode,
        branch_limit: int,
    ) -> RetrievalRouteContext:
        """Build query routing context
        Computes feature cues expansion targets coverage plan and routing attribution"""
        routing = self.feature_scorer.decide(query, mode=mode, branch_limit=branch_limit)
        feature_scores = routing.feature_scores
        composition_cue = feature_scores.get("composition_cue", 0.0)
        negation_cue = feature_scores.get("negation_cue", 0.0)
        conflict_cue = feature_scores.get("conflict_cue", 0.0)
        temporal_cue = feature_scores.get("temporal_cue", 0.0)
        ambiguity_cue = feature_scores.get("entity_ambiguity_cue", 0.0)
        query_entities = self._expand_query_entities(agent_id, self._query_entities(query))
        feature_active_min = self.feature_scorer.thresholds.get("feature_active_min", 0.34)
        expansion_target = max(2, int(self.feature_scorer.resolver_thresholds.get("expansion_branch_target", 2.0)))
        supplemental_weights = self.feature_scorer.supplemental_weights
        composition_query = composition_cue >= feature_active_min
        negation_sensitive_query = negation_cue >= feature_active_min
        conflict_query = conflict_cue >= feature_active_min
        coverage_query = max(composition_cue, negation_cue) >= self.feature_scorer.thresholds.get("coverage_min", 0.45)
        coverage_plan = build_coverage_plan(
            query=query,
            feature_scores=feature_scores,
            query_entities=query_entities,
            feature_scorer=self.feature_scorer,
        )
        routing_attribution: dict[str, object] = {
            "routing_strategy": routing.strategy,
            "query_feature_scores": feature_scores,
            "fired_rules": routing.fired_rules,
            "routing_reason": routing.reason,
            "hierarchical_score": routing.hierarchical_score,
            "coverage_plan": {
                "min_leaf_count": coverage_plan.min_leaf_count,
                "required_facets": list(coverage_plan.required_facets),
                "communication_facets": list(coverage_plan.communication_facets),
                "communication_min_hits": coverage_plan.communication_min_hits,
                "enforce_entity_thread": coverage_plan.enforce_entity_thread,
            },
        }
        return RetrievalRouteContext(
            routing=routing,
            temporal_cue=temporal_cue,
            ambiguity_cue=ambiguity_cue,
            query_entities=list(query_entities),
            feature_active_min=feature_active_min,
            expansion_target=expansion_target,
            supplemental_weights=supplemental_weights,
            composition_query=composition_query,
            negation_sensitive_query=negation_sensitive_query,
            conflict_query=conflict_query,
            coverage_query=coverage_query,
            coverage_plan=coverage_plan,
            routing_attribution=routing_attribution,
        )

    def attempt_leaf_first(
        self,
        *,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        route_context: RetrievalRouteContext,
    ) -> LeafFirstOutcome:
        """Leaf first phase for quick confident answers
        Handles revision leaf path and confidence based short circuit logic"""
        routing = route_context.routing
        temporal_cue = route_context.temporal_cue
        ambiguity_cue = route_context.ambiguity_cue
        feature_active_min = route_context.feature_active_min
        query_entities = set(route_context.query_entities)
        eval_context = self._build_leaf_first_evaluation_context(
            agent_id=agent_id,
            query=query,
            query_time=query_time,
            temporal_cue=temporal_cue,
            feature_active_min=feature_active_min,
            query_entities=query_entities,
        )
        signals = self._build_leaf_first_signals(
            query=query,
            mode=mode,
            routing=routing,
            query_entities=query_entities,
            temporal_cue=temporal_cue,
            ambiguity_cue=ambiguity_cue,
            feature_active_min=feature_active_min,
            eval_context=eval_context,
        )

        if (
            signals.revision_leaf_first_query
            and eval_context.top_leaf_probe
            and not signals.revision_needs_expansion
            and not signals.disambiguation_pressure
        ):
            top_leaf = eval_context.top_leaf_probe[0]
            selected = [top_leaf]
            revision_enrichment = self._select_revision_enrichment_leaf(
                query=query,
                top_leaf=top_leaf,
                ranked_leaves=eval_context.ranked_leaf_candidates,
                token_budget=token_budget,
                enabled=routing.enable_revision_enrichment,
            )
            if revision_enrichment is not None:
                selected.append(revision_enrichment)
            trace_entries: list[RetrievalTraceEntry] = []
            for item in selected:
                self.store.mark_accessed(item.node.node_id, item.relevance, item.recency, query_time)
                trace_entries.append(
                    make_retrieval_trace_entry(
                        item,
                        selected_as="query_router_flat",
                        selection_reason=f"Feature scorer selected revision leaf-first strategy. {routing.reason}",
                    )
                )
            if len(selected) > 1:
                trace_entries[-1].selection_reason = (
                    "Added a second revision leaf because it contributes launch/correction phrasing missing from the top leaf."
                )
            return self._build_leaf_first_outcome(
                handled=True,
                selected=selected,
                max_depth=1,
                trace_entries=trace_entries,
                eval_context=eval_context,
                signals=signals,
            )

        if self._should_confident_leaf_short_circuit(
            mode=mode,
            route_context=route_context,
            query_entities=query_entities,
            temporal_cue=temporal_cue,
            ambiguity_cue=ambiguity_cue,
            feature_active_min=feature_active_min,
            eval_context=eval_context,
            signals=signals,
        ):
            top_leaf = eval_context.top_leaf_probe[0]
            self.store.mark_accessed(top_leaf.node.node_id, top_leaf.relevance, top_leaf.recency, query_time)
            trace_entry = make_retrieval_trace_entry(
                top_leaf,
                selected_as="query_router_flat",
                selection_reason="Feature scorer selected leaf-first confidence route.",
            )
            return self._build_leaf_first_outcome(
                handled=True,
                selected=[top_leaf],
                max_depth=1,
                trace_entries=[trace_entry],
                eval_context=eval_context,
                signals=signals,
            )

        return self._build_leaf_first_outcome(
            handled=False,
            selected=[],
            max_depth=0,
            trace_entries=[],
            eval_context=eval_context,
            signals=signals,
        )

    def rank_summaries_and_branches(
        self,
        *,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        branch_limit: int,
        route_context: RetrievalRouteContext,
        leaf_outcome: LeafFirstOutcome,
    ) -> BranchRankingOutcome:
        """Run branch ranking and cache full result for final stage"""
        selected, max_depth, trace_entries, routing_attribution = self._retrieve_legacy(
            agent_id=agent_id,
            query=query,
            query_time=query_time,
            mode=mode,
            token_budget=token_budget,
            branch_limit=branch_limit,
        )
        self._pipeline_cached_result = (selected, max_depth, trace_entries, routing_attribution)
        self._pipeline_cached_request = (agent_id, query, query_time, token_budget, branch_limit)
        consumed = sum(item.node.token_count for item in selected)
        return BranchRankingOutcome(
            picked=selected,
            consumed=consumed,
            max_depth=max_depth,
            trace_entries=trace_entries,
        )

    def apply_supplemental_selection(
        self,
        *,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        route_context: RetrievalRouteContext,
        leaf_outcome: LeafFirstOutcome,
        picked: list[CandidateScore],
        consumed: int,
        trace_entries: list[RetrievalTraceEntry],
    ) -> SupplementalSelectionOutcome:
        """Pass through selected nodes from rank stage"""
        return SupplementalSelectionOutcome(
            picked=picked,
            trace_entries=trace_entries,
        )

    def build_trace_and_diagnostics(
        self,
        *,
        agent_id: str,
        query: str,
        query_time: datetime,
        token_budget: int,
        branch_limit: int,
        detail_query: bool,
        picked: list[CandidateScore],
        max_depth: int,
        trace_entries: list[RetrievalTraceEntry],
        routing_attribution: dict[str, object],
    ) -> tuple[list[CandidateScore], int, list[RetrievalTraceEntry], dict[str, object]]:
        """Finalize picks and handle fallback when needed"""
        cached_request = self._pipeline_cached_request
        if cached_request == (agent_id, query, query_time, token_budget, branch_limit) and self._pipeline_cached_result is not None:
            result = self._pipeline_cached_result
            self._pipeline_cached_request = None
            self._pipeline_cached_result = None
            return result

        if not picked:
            fallback_limit = min(branch_limit, 2) if detail_query else 1
            fallback = self.flat_retriever.retrieve(agent_id, query, query_time, token_budget, limit=fallback_limit)
            fallback_entries = [
                make_retrieval_trace_entry(
                    item,
                    selected_as="flat_fallback",
                    selection_reason="No summary branch survived ranking, so flat retrieval was used.",
                )
                for item in fallback
            ]
            return fallback, 1, fallback_entries, routing_attribution
        ranked = sorted(picked, key=lambda item: item.score, reverse=True)
        return ranked, max_depth, trace_entries, routing_attribution

    def _build_leaf_first_evaluation_context(
        self,
        *,
        agent_id: str,
        query: str,
        query_time: datetime,
        temporal_cue: float,
        feature_active_min: float,
        query_entities: set[str],
    ) -> LeafFirstEvaluationContext:
        """Compute leaf probe detail flags and confidence"""
        detail_query = self._is_detail_query(query)
        revision_query = temporal_cue >= feature_active_min
        cross_branch_revision_query = temporal_cue >= self.feature_scorer.thresholds.get("hierarchy_expand_min", 0.48)
        ranked_leaf_candidates = self._rank_leaf_candidates(
            agent_id,
            query,
            query_time,
            query_entities=query_entities,
        )
        top_leaf_probe = ranked_leaf_candidates[:2]
        low_confidence = self._is_low_confidence(top_leaf_probe)
        return LeafFirstEvaluationContext(
            detail_query=detail_query,
            revision_query=revision_query,
            cross_branch_revision_query=cross_branch_revision_query,
            ranked_leaf_candidates=ranked_leaf_candidates,
            top_leaf_probe=top_leaf_probe,
            low_confidence=low_confidence,
        )

    def _build_leaf_first_signals(
        self,
        *,
        query: str,
        mode: QueryMode,
        routing: QueryRoutingDecision,
        query_entities: set[str],
        temporal_cue: float,
        ambiguity_cue: float,
        feature_active_min: float,
        eval_context: LeafFirstEvaluationContext,
    ) -> LeafFirstSignals:
        """Compute disambiguation and revision expansion signals"""
        named_person_comm_query = self._is_named_person_communication_query(query, query_entities)
        competing_person_threads = self._has_competing_person_threads(eval_context.ranked_leaf_candidates, query_entities)
        target_person_strategy_resolver = named_person_comm_query and competing_person_threads
        disambiguation_pressure = self._has_disambiguation_pressure(
            query=query,
            query_entities=query_entities,
            top_leaf_probe=eval_context.top_leaf_probe,
            temporal_cue=temporal_cue,
            ambiguity_cue=ambiguity_cue,
            feature_active_min=feature_active_min,
            low_confidence=eval_context.low_confidence,
        )
        disambiguation_pressure = disambiguation_pressure or target_person_strategy_resolver
        revision_leaf_first_query = (
            mode == QueryMode.BALANCED
            and routing.strategy == "revision_leaf_first"
            and self._is_revision_leaf_first_query(query)
        )
        revision_top_leaf_has_cues = (
            bool(eval_context.top_leaf_probe)
            and self._leaf_satisfies_revision_slot_cues(query, eval_context.top_leaf_probe[0].node.text)
        )
        revision_top_leaf_missing_cues = bool(eval_context.top_leaf_probe) and not revision_top_leaf_has_cues
        revision_top_leaf_entity_mismatch = (
            bool(eval_context.top_leaf_probe)
            and bool(query_entities)
            and not self._is_entity_aligned(eval_context.top_leaf_probe[0].node, query_entities)
        )
        revision_low_confidence_requires_expansion = eval_context.low_confidence and not revision_top_leaf_has_cues
        revision_needs_expansion = revision_leaf_first_query and (
            not eval_context.top_leaf_probe
            or revision_low_confidence_requires_expansion
            or revision_top_leaf_missing_cues
            or revision_top_leaf_entity_mismatch
            or disambiguation_pressure
        )
        routing_updates: dict[str, object] = {
            "target_person_strategy_resolver": float(target_person_strategy_resolver),
            "disambiguation_pressure": float(disambiguation_pressure),
        }
        return LeafFirstSignals(
            target_person_strategy_resolver=target_person_strategy_resolver,
            disambiguation_pressure=disambiguation_pressure,
            revision_leaf_first_query=revision_leaf_first_query,
            revision_needs_expansion=revision_needs_expansion,
            routing_updates=routing_updates,
        )

    def _should_confident_leaf_short_circuit(
        self,
        *,
        mode: QueryMode,
        route_context: RetrievalRouteContext,
        query_entities: set[str],
        temporal_cue: float,
        ambiguity_cue: float,
        feature_active_min: float,
        eval_context: LeafFirstEvaluationContext,
        signals: LeafFirstSignals,
    ) -> bool:
        """Check if top leaf is safe to return directly"""
        return (
            mode == QueryMode.BALANCED
            and bool(eval_context.top_leaf_probe)
            and not eval_context.detail_query
            and not route_context.composition_query
            and not route_context.negation_sensitive_query
            and not route_context.conflict_query
            and not route_context.coverage_plan.requires_multi_leaf
            and not eval_context.low_confidence
            and not signals.disambiguation_pressure
            and not signals.target_person_strategy_resolver
            and ambiguity_cue < feature_active_min
            and temporal_cue < self.feature_scorer.thresholds.get("revision_leaf_min", 0.45)
            and (not query_entities or self._is_entity_aligned(eval_context.top_leaf_probe[0].node, query_entities))
        )

    def _build_leaf_first_outcome(
        self,
        *,
        handled: bool,
        selected: list[CandidateScore],
        max_depth: int,
        trace_entries: list[RetrievalTraceEntry],
        eval_context: LeafFirstEvaluationContext,
        signals: LeafFirstSignals,
    ) -> LeafFirstOutcome:
        """Pack leaf phase outputs for next pipeline stage"""
        return LeafFirstOutcome(
            handled=handled,
            selected=selected,
            max_depth=max_depth,
            trace_entries=trace_entries,
            detail_query=eval_context.detail_query,
            revision_query=eval_context.revision_query,
            cross_branch_revision_query=eval_context.cross_branch_revision_query,
            ranked_leaf_candidates=eval_context.ranked_leaf_candidates,
            low_confidence=eval_context.low_confidence,
            target_person_strategy_resolver=signals.target_person_strategy_resolver,
            disambiguation_pressure=signals.disambiguation_pressure,
            revision_needs_expansion=signals.revision_needs_expansion,
            routing_attribution_updates=signals.routing_updates,
        )

    def _retrieve_legacy(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        branch_limit: int,
    ) -> tuple[list[CandidateScore], int, list[RetrievalTraceEntry], dict[str, object]]:
        routing = self.feature_scorer.decide(query, mode=mode, branch_limit=branch_limit)
        feature_scores = routing.feature_scores
        composition_cue = feature_scores.get("composition_cue", 0.0)
        negation_cue = feature_scores.get("negation_cue", 0.0)
        conflict_cue = feature_scores.get("conflict_cue", 0.0)
        temporal_cue = feature_scores.get("temporal_cue", 0.0)
        ambiguity_cue = feature_scores.get("entity_ambiguity_cue", 0.0)
        query_entities = self._expand_query_entities(agent_id, self._query_entities(query))
        feature_active_min = self.feature_scorer.thresholds.get("feature_active_min", 0.34)
        expansion_target = max(2, int(self.feature_scorer.resolver_thresholds.get("expansion_branch_target", 2.0)))
        supplemental_weights = self.feature_scorer.supplemental_weights
        composition_query = composition_cue >= feature_active_min
        negation_sensitive_query = negation_cue >= feature_active_min
        conflict_query = conflict_cue >= feature_active_min
        coverage_query = max(composition_cue, negation_cue) >= self.feature_scorer.thresholds.get("coverage_min", 0.45)
        coverage_plan = self._build_coverage_plan(
            query=query,
            feature_scores=feature_scores,
            query_entities=query_entities,
        )

        routing_attribution = {
            "routing_strategy": routing.strategy,
            "query_feature_scores": feature_scores,
            "fired_rules": routing.fired_rules,
            "routing_reason": routing.reason,
            "hierarchical_score": routing.hierarchical_score,
            "coverage_plan": {
                "min_leaf_count": coverage_plan.min_leaf_count,
                "required_facets": list(coverage_plan.required_facets),
                "communication_facets": list(coverage_plan.communication_facets),
                "communication_min_hits": coverage_plan.communication_min_hits,
                "enforce_entity_thread": coverage_plan.enforce_entity_thread,
            },
        }

        if mode == QueryMode.BALANCED and routing.strategy == "flat_top1":
            routed = self.flat_retriever.retrieve(agent_id, query, query_time, token_budget, limit=1)
            routed_entries = [
                RetrievalTraceEntry(
                    node_id=item.node.node_id,
                    level=item.node.level,
                    node_type=item.node.node_type,
                    score=item.score,
                    relevance_score=item.relevance,
                    recency_score=item.recency,
                    importance_score=item.node.importance_score,
                    branch_root_id=None,
                    selected_as="query_router_flat",
                    selection_reason=f"Routed by feature scorer to flat top-1. {routing.reason}",
                )
                for item in routed
            ]
            return routed, 1, routed_entries, routing_attribution

        detail_query = self._is_detail_query(query)
        revision_query = temporal_cue >= feature_active_min
        cross_branch_revision_query = temporal_cue >= self.feature_scorer.thresholds.get("hierarchy_expand_min", 0.48)
        ranked_leaf_candidates = self._rank_leaf_candidates(agent_id, query, query_time, query_entities=query_entities)
        top_leaf_probe = ranked_leaf_candidates[:2]
        low_confidence = self._is_low_confidence(top_leaf_probe)
        named_person_comm_query = self._is_named_person_communication_query(query, query_entities)
        competing_person_threads = self._has_competing_person_threads(ranked_leaf_candidates, query_entities)
        target_person_strategy_resolver = named_person_comm_query and competing_person_threads
        routing_attribution["target_person_strategy_resolver"] = float(target_person_strategy_resolver)
        disambiguation_pressure = self._has_disambiguation_pressure(
            query=query,
            query_entities=query_entities,
            top_leaf_probe=top_leaf_probe,
            temporal_cue=temporal_cue,
            ambiguity_cue=ambiguity_cue,
            feature_active_min=feature_active_min,
            low_confidence=low_confidence,
        )
        disambiguation_pressure = disambiguation_pressure or target_person_strategy_resolver
        routing_attribution["disambiguation_pressure"] = float(disambiguation_pressure)
        revision_leaf_first_query = (
            mode == QueryMode.BALANCED
            and routing.strategy == "revision_leaf_first"
            and self._is_revision_leaf_first_query(query)
        )
        revision_top_leaf_has_cues = (
            bool(top_leaf_probe)
            and self._leaf_satisfies_revision_slot_cues(query, top_leaf_probe[0].node.text)
        )
        revision_top_leaf_missing_cues = bool(top_leaf_probe) and not revision_top_leaf_has_cues
        revision_top_leaf_entity_mismatch = (
            bool(top_leaf_probe)
            and bool(query_entities)
            and not self._is_entity_aligned(top_leaf_probe[0].node, query_entities)
        )
        revision_low_confidence_requires_expansion = low_confidence and not revision_top_leaf_has_cues
        revision_needs_expansion = revision_leaf_first_query and (
            not top_leaf_probe
            or revision_low_confidence_requires_expansion
            or revision_top_leaf_missing_cues
            or revision_top_leaf_entity_mismatch
            or disambiguation_pressure
        )

        if revision_leaf_first_query and top_leaf_probe and not revision_needs_expansion and not disambiguation_pressure:
            top_leaf = top_leaf_probe[0]
            selected = [top_leaf]
            revision_enrichment = self._select_revision_enrichment_leaf(
                query=query,
                top_leaf=top_leaf,
                ranked_leaves=ranked_leaf_candidates,
                token_budget=token_budget,
                enabled=routing.enable_revision_enrichment,
            )
            if revision_enrichment is not None:
                selected.append(revision_enrichment)
            trace_entries: list[RetrievalTraceEntry] = []
            for item in selected:
                self.store.mark_accessed(item.node.node_id, item.relevance, item.recency, query_time)
                trace_entries.append(
                    RetrievalTraceEntry(
                        node_id=item.node.node_id,
                        level=item.node.level,
                        node_type=item.node.node_type,
                        score=item.score,
                        relevance_score=item.relevance,
                        recency_score=item.recency,
                        importance_score=item.node.importance_score,
                        branch_root_id=None,
                        selected_as="query_router_flat",
                        selection_reason=f"Feature scorer selected revision leaf-first strategy. {routing.reason}",
                    )
                )
            if len(selected) > 1:
                trace_entries[-1].selection_reason = (
                    "Added a second revision leaf because it contributes launch/correction phrasing missing from the top leaf."
                )
            return selected, 1, trace_entries, routing_attribution

        if (
            mode == QueryMode.BALANCED
            and top_leaf_probe
            and not detail_query
            and not composition_query
            and not negation_sensitive_query
            and not conflict_query
            and not coverage_plan.requires_multi_leaf
            and not low_confidence
            and not disambiguation_pressure
            and not target_person_strategy_resolver
            and ambiguity_cue < feature_active_min
            and temporal_cue < self.feature_scorer.thresholds.get("revision_leaf_min", 0.45)
            and (not query_entities or self._is_entity_aligned(top_leaf_probe[0].node, query_entities))
        ):
            top_leaf = top_leaf_probe[0]
            self.store.mark_accessed(top_leaf.node.node_id, top_leaf.relevance, top_leaf.recency, query_time)
            trace_entry = RetrievalTraceEntry(
                node_id=top_leaf.node.node_id,
                level=top_leaf.node.level,
                node_type=top_leaf.node.node_type,
                score=top_leaf.score,
                relevance_score=top_leaf.relevance,
                recency_score=top_leaf.recency,
                importance_score=top_leaf.node.importance_score,
                branch_root_id=None,
                selected_as="query_router_flat",
                selection_reason="Feature scorer selected leaf-first confidence route.",
            )
            return [top_leaf], 1, [trace_entry], routing_attribution

        summaries = self.store.list_nodes(agent_id=agent_id, level=MemoryLevel.L1)
        summary_scores: list[CandidateScore] = []
        trace_entries: list[RetrievalTraceEntry] = []
        for node in summaries:
            rel = relevance_score(query, node.text)
            rec = recency_score(query_time, node.timestamp_end)
            score = statistics.fmean([rel * 1.4, rec * 0.7, normalize_importance(node.importance_score)])
            summary_scores.append(CandidateScore(node=node, score=score, relevance=rel, recency=rec))
        adaptive_branch_limit = branch_limit
        if mode == QueryMode.BALANCED:
            adaptive_branch_limit = max(1, routing.branch_limit_override)
            if (
                low_confidence
                or disambiguation_pressure
                or cross_branch_revision_query
                or revision_needs_expansion
                or coverage_plan.requires_multi_leaf
            ):
                adaptive_branch_limit = max(adaptive_branch_limit, expansion_target)
            adaptive_branch_limit = min(adaptive_branch_limit, branch_limit)

        ranked_summaries = sorted(summary_scores, key=lambda item: item.score, reverse=True)[:adaptive_branch_limit]
        picked: list[CandidateScore] = []
        picked_ids: set[str] = set()
        consumed = 0
        max_depth = 1 if ranked_summaries else 0
        branch_count = max(len(ranked_summaries), 1)
        branch_budget = max(1, math.floor(token_budget / branch_count))

        for index, summary in enumerate(ranked_summaries):
            remaining = token_budget - consumed
            if remaining <= 0:
                break
            branches_left = max(len(ranked_summaries) - index, 1)
            branch_allowance = min(remaining, max(branch_budget, math.floor(remaining / branches_left)))
            children = [self.store.get_node(child_id) for child_id in summary.node.child_ids]
            child_scores: list[CandidateScore] = []
            for child in children:
                if child is None:
                    continue
                rel = relevance_score(query, child.text)
                rec = recency_score(query_time, child.timestamp_end)
                score = statistics.fmean([rel * 1.2, rec * 0.4, normalize_importance(child.importance_score)])
                score += self._entity_alignment_adjustment(child, query_entities)
                child_scores.append(CandidateScore(node=child, score=score, relevance=rel, recency=rec))
            child_scores = sorted(child_scores, key=lambda item: item.score, reverse=True)
            best_child = next((child for child in child_scores if child.node.token_count <= branch_allowance), None)

            descend = False
            if mode == QueryMode.DRILL_DOWN:
                descend = best_child is not None
            elif mode == QueryMode.BALANCED:
                child_close_to_summary = best_child is not None and best_child.score >= summary.score * 0.95
                descend = best_child is not None and (
                    composition_query
                    or conflict_query
                    or negation_sensitive_query
                    or ambiguity_cue >= feature_active_min
                    or low_confidence
                    or cross_branch_revision_query
                    or revision_needs_expansion
                    or coverage_plan.requires_multi_leaf
                    or (detail_query and summary.relevance < 0.72)
                    or child_close_to_summary
                    or (revision_query and best_child.score >= summary.score * 0.92)
                )

            if descend:
                max_depth = max(max_depth, 2)
                enforce_entity_anchor = (
                    coverage_plan.enforce_entity_thread or target_person_strategy_resolver
                ) and ambiguity_cue < feature_active_min
                if mode == QueryMode.DRILL_DOWN:
                    children_to_add = child_scores[:2]
                elif composition_query:
                    children_to_add = self._select_children_for_query(
                        query,
                        child_scores,
                        max_children=1,
                        query_entities=query_entities,
                        enforce_entity_anchor=enforce_entity_anchor,
                        required_facets=set(coverage_plan.required_facets),
                    )
                elif coverage_query or coverage_plan.requires_multi_leaf:
                    children_to_add = self._select_children_for_query(
                        query,
                        child_scores,
                        max_children=1,
                        query_entities=query_entities,
                        enforce_entity_anchor=enforce_entity_anchor,
                        required_facets=set(coverage_plan.required_facets),
                    )
                else:
                    children_to_add = child_scores[:1]
                added_child = False
                branch_consumed = 0
                for child in children_to_add:
                    if child.node.node_id in picked_ids:
                        continue
                    if child.node.token_count > branch_allowance - branch_consumed:
                        continue
                    consumed += child.node.token_count
                    branch_consumed += child.node.token_count
                    self.store.mark_accessed(child.node.node_id, child.relevance, child.recency, query_time)
                    picked.append(child)
                    picked_ids.add(child.node.node_id)
                    added_child = True
                    trace_entries.append(
                        RetrievalTraceEntry(
                            node_id=child.node.node_id,
                            level=child.node.level,
                            node_type=child.node.node_type,
                            score=child.score,
                            relevance_score=child.relevance,
                            recency_score=child.recency,
                            importance_score=child.node.importance_score,
                            branch_root_id=summary.node.node_id,
                            selected_as="supporting_leaf",
                            selection_reason="Descended into branch because leaf evidence is expected to be more reliable than summary-only retrieval.",
                        )
                    )
                if added_child:
                    continue

            if summary.node.token_count > branch_allowance:
                continue
            if summary.node.node_id in picked_ids:
                continue
            picked.append(summary)
            picked_ids.add(summary.node.node_id)
            consumed += summary.node.token_count
            self.store.mark_accessed(summary.node.node_id, summary.relevance, summary.recency, query_time)
            trace_entries.append(
                RetrievalTraceEntry(
                    node_id=summary.node.node_id,
                    level=summary.node.level,
                    node_type=summary.node.node_type,
                    score=summary.score,
                    relevance_score=summary.relevance,
                    recency_score=summary.recency,
                    importance_score=summary.node.importance_score,
                    branch_root_id=summary.node.node_id,
                    selected_as="summary",
                    selection_reason="Selected as the branch summary under the per-branch budget.",
                )
            )

        # For coverage-heavy prompts, add missing coverage leaves if the first pass under-covered.
        should_expand_coverage = (
            mode == QueryMode.BALANCED
            and (
                routing.enable_coverage_expansion
                or coverage_plan.requires_multi_leaf
                or coverage_plan.has_required_facets
                or coverage_plan.communication_min_hits > 0
                or target_person_strategy_resolver
                or ambiguity_cue >= feature_active_min
                or (coverage_plan.enforce_entity_thread and bool(query_entities))
            )
        )
        if should_expand_coverage:
            used_ids = {item.node.node_id for item in picked}
            leaf_count = sum(1 for item in picked if item.node.level == MemoryLevel.L0)
            coverage_fn = self._generic_coverage_keys
            covered: set[str] = set()
            for item in picked:
                if item.node.level == MemoryLevel.L0:
                    covered.update(coverage_fn(query, item.node.text))
            required_facets = set(coverage_plan.required_facets)
            communication_facets = set(coverage_plan.communication_facets)
            enforce_entity_thread = coverage_plan.enforce_entity_thread or target_person_strategy_resolver
            while True:
                needs_polarity_balance = self._needs_negation_polarity_balance(query=query, picked=picked)
                need_negative_polarity, need_affirmative_polarity = self._missing_commitment_polarity(picked)
                needs_entity_disambiguation = self._needs_entity_disambiguation_support(
                    query_entities=query_entities,
                    picked=picked,
                    ambiguity_cue=ambiguity_cue,
                    feature_active_min=feature_active_min,
                    low_confidence=low_confidence,
                )
                target_leaf_count = self._dynamic_target_leaf_count(
                    leaf_count=leaf_count,
                    covered=covered,
                    required_facets=required_facets,
                    communication_facets=communication_facets,
                    communication_min_hits=coverage_plan.communication_min_hits,
                    low_confidence=low_confidence,
                    routing_expansion=routing.enable_coverage_expansion,
                    enforce_entity_thread=enforce_entity_thread,
                    query_entities=query_entities,
                    picked=picked,
                    needs_polarity_balance=negation_sensitive_query and needs_polarity_balance,
                    needs_entity_disambiguation=needs_entity_disambiguation,
                    expansion_target=expansion_target,
                )
                if leaf_count >= target_leaf_count:
                    break
                missing_required = required_facets - covered
                comm_hits = len(communication_facets & covered)
                communication_gap = comm_hits < coverage_plan.communication_min_hits
                utility_threshold = self._supplemental_utility_threshold(
                    leaf_count=leaf_count,
                    missing_required=missing_required,
                    communication_gap=communication_gap,
                    needs_polarity_balance=negation_sensitive_query and needs_polarity_balance,
                    needs_entity_disambiguation=needs_entity_disambiguation,
                    temporal_cue=temporal_cue,
                    ambiguity_cue=ambiguity_cue,
                    low_confidence=low_confidence,
                    feature_active_min=feature_active_min,
                )
                best_candidate: CandidateScore | None = None
                best_keys: set[str] = set()
                best_utility = -1.0
                for candidate in ranked_leaf_candidates:
                    if candidate.node.node_id in used_ids:
                        continue
                    if consumed + candidate.node.token_count > token_budget:
                        continue
                    candidate_keys = coverage_fn(query, candidate.node.text)
                    new_coverage = candidate_keys - covered
                    required_hits = candidate_keys & missing_required
                    adds_comm = (
                        comm_hits < coverage_plan.communication_min_hits
                        and bool((candidate_keys & communication_facets) - covered)
                    )
                    provides_polarity_signal = (
                        needs_polarity_balance
                        and (
                            (need_affirmative_polarity and self._has_affirmative_commitment(candidate.node.text))
                            or (need_negative_polarity and self._has_negative_commitment(candidate.node.text))
                        )
                    )
                    is_entity_aligned = self._is_entity_aligned(candidate.node, query_entities)
                    shares_thread = (
                        self._shares_thread_with_aligned_leaf(candidate.node, picked, query_entities)
                        if query_entities
                        else False
                    )
                    provides_disambiguation_signal = needs_entity_disambiguation and (is_entity_aligned or shares_thread)
                    if target_person_strategy_resolver and query_entities and not is_entity_aligned:
                        continue
                    if enforce_entity_thread and query_entities and not is_entity_aligned:
                        provides_required_signal = (
                            bool(required_hits) or adds_comm or provides_polarity_signal or provides_disambiguation_signal
                        )
                        allow_non_aligned_support = (
                            leaf_count > 0
                            and self._has_entity_thread_anchor(picked, query_entities)
                            and not self._has_negated_query_entity(candidate.node.text, query_entities)
                            and (
                                not self._has_conflicting_named_entity(candidate.node, query_entities)
                                or provides_required_signal
                            )
                            and (shares_thread or provides_required_signal)
                        )
                        if not allow_non_aligned_support:
                            continue
                    if (
                        leaf_count > 0
                        and not new_coverage
                        and not required_hits
                        and not adds_comm
                        and not provides_polarity_signal
                        and not provides_disambiguation_signal
                    ):
                        continue
                    utility = candidate.score
                    utility_bonus = 0.0
                    utility_bonus += supplemental_weights.get("coverage_bonus_per_key", 0.06) * len(new_coverage)
                    utility_bonus += supplemental_weights.get("required_bonus_per_key", 0.12) * len(required_hits)
                    if adds_comm:
                        utility_bonus += supplemental_weights.get("communication_bonus", 0.10)
                    if provides_polarity_signal:
                        utility_bonus += supplemental_weights.get("polarity_bonus", 0.10)
                    if provides_disambiguation_signal:
                        utility_bonus += supplemental_weights.get("disambiguation_bonus", 0.10)
                    if is_entity_aligned:
                        utility_bonus += supplemental_weights.get("entity_aligned_bonus", 0.03)
                    # Tightening: require non-trivial marginal utility before adding leaf #2+.
                    if leaf_count > 0 and utility_bonus < utility_threshold:
                        continue
                    utility += utility_bonus
                    if utility > best_utility:
                        best_candidate = candidate
                        best_keys = candidate_keys
                        best_utility = utility
                if best_candidate is None:
                    break
                picked.append(best_candidate)
                consumed += best_candidate.node.token_count
                leaf_count += 1
                used_ids.add(best_candidate.node.node_id)
                covered.update(best_keys)
                self.store.mark_accessed(best_candidate.node.node_id, best_candidate.relevance, best_candidate.recency, query_time)
                trace_entries.append(
                    RetrievalTraceEntry(
                        node_id=best_candidate.node.node_id,
                        level=best_candidate.node.level,
                        node_type=best_candidate.node.node_type,
                        score=best_candidate.score,
                        relevance_score=best_candidate.relevance,
                        recency_score=best_candidate.recency,
                        importance_score=best_candidate.node.importance_score,
                        branch_root_id=None,
                        selected_as="supporting_leaf",
                        selection_reason="Added supplemental leaf to satisfy coverage-plan facets for a multi-fact query.",
                    )
                )

        if not picked:
            fallback_limit = min(branch_limit, 2) if detail_query else 1
            fallback = self.flat_retriever.retrieve(agent_id, query, query_time, token_budget, limit=fallback_limit)
            fallback_entries = [
                RetrievalTraceEntry(
                    node_id=item.node.node_id,
                    level=item.node.level,
                    node_type=item.node.node_type,
                    score=item.score,
                    relevance_score=item.relevance,
                    recency_score=item.recency,
                    importance_score=item.node.importance_score,
                    branch_root_id=None,
                    selected_as="flat_fallback",
                    selection_reason="No summary branch survived ranking, so flat retrieval was used.",
                )
                for item in fallback
            ]
            return fallback, 1, fallback_entries, routing_attribution
        ranked = sorted(picked, key=lambda item: item.score, reverse=True)
        return ranked, max_depth, trace_entries, routing_attribution

    def _rank_leaf_candidates(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        query_entities: set[str] | None = None,
    ) -> list[CandidateScore]:
        nodes = self.store.list_nodes(agent_id=agent_id, level=MemoryLevel.L0)
        candidates: list[CandidateScore] = []
        query_entities = query_entities or set()
        for node in nodes:
            rel = relevance_score(query, node.text)
            rec = recency_score(query_time, node.timestamp_end)
            score = statistics.fmean([rel, rec, normalize_importance(node.importance_score)])
            score += self._entity_alignment_adjustment(node, query_entities)
            candidates.append(CandidateScore(node=node, score=score, relevance=rel, recency=rec))
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _is_low_confidence(self, ranked_leaves: list[CandidateScore]) -> bool:
        if len(ranked_leaves) < 2:
            return False
        margin = float(self.feature_scorer.resolver_thresholds.get("low_confidence_margin", 0.08))
        if (ranked_leaves[0].score - ranked_leaves[1].score) > margin:
            return False
        shared_entities = set(ranked_leaves[0].node.entities) & set(ranked_leaves[1].node.entities)
        return not shared_entities

    def _is_named_person_communication_query(self, query: str, query_entities: set[str]) -> bool:
        if not query_entities:
            return False
        lowered = query.lower()
        communication_terms = ("communication", "communicate", "strategy", "approach", "with")
        return any(term in lowered for term in communication_terms)

    def _has_competing_person_threads(self, ranked_leaves: list[CandidateScore], query_entities: set[str]) -> bool:
        if not query_entities or not ranked_leaves:
            return False
        top_score = ranked_leaves[0].score
        window = max(2, int(self.feature_scorer.resolver_thresholds.get("competing_person_window", 8.0)))
        ratio = float(self.feature_scorer.resolver_thresholds.get("competing_person_score_ratio", 0.55))
        gap = float(self.feature_scorer.resolver_thresholds.get("competing_person_score_gap", 0.25))
        competing_candidates = ranked_leaves[:window]
        has_aligned = any(self._is_entity_aligned(candidate.node, query_entities) for candidate in competing_candidates)
        has_conflicting = any(
            (
                (candidate.score >= top_score * ratio)
                or ((top_score - candidate.score) <= gap)
            )
            and (not self._is_entity_aligned(candidate.node, query_entities))
            and self._has_conflicting_named_entity(candidate.node, query_entities)
            for candidate in competing_candidates
        )
        return has_aligned and has_conflicting

    def _has_disambiguation_pressure(
        self,
        *,
        query: str,
        query_entities: set[str],
        top_leaf_probe: list[CandidateScore],
        temporal_cue: float,
        ambiguity_cue: float,
        feature_active_min: float,
        low_confidence: bool,
    ) -> bool:
        if not query_entities:
            return False
        lowered = query.lower()
        has_pronoun_reference = bool(re.search(r"\b(?:he|she|they|him|her|them)\b", lowered))
        temporal_dominant = temporal_cue >= self.feature_scorer.thresholds.get("revision_leaf_min", 0.45)
        if temporal_dominant and ambiguity_cue < feature_active_min and not has_pronoun_reference:
            return False
        if ambiguity_cue >= feature_active_min:
            return True
        if has_pronoun_reference:
            return True
        if not top_leaf_probe:
            return True
        top_leaf = top_leaf_probe[0]
        if not self._is_entity_aligned(top_leaf.node, query_entities):
            return True
        if len(top_leaf_probe) < 2:
            return False
        runner_up = top_leaf_probe[1]
        close_margin = (
            top_leaf.score - runner_up.score
        ) <= float(self.feature_scorer.resolver_thresholds.get("disambiguation_close_margin", 0.08))
        runner_up_mismatch = not self._is_entity_aligned(runner_up.node, query_entities)
        return runner_up_mismatch and (close_margin or low_confidence)

    def _is_detail_query(self, query: str) -> bool:
        lowered = query.lower()
        return any(
            token in lowered
            for token in ["when", "what exactly", "which", "latest", "changed", "say", "details", "specific", "why"]
        )

    def _query_terms(self, query: str) -> set[str]:
        return set(re.findall(r"[a-z]+", query.lower()))

    def _filter_entity_tokens(self, entities: set[str]) -> set[str]:
        stop_entities = {
            "what",
            "when",
            "where",
            "who",
            "why",
            "how",
            "which",
            "from",
            "for",
            "with",
            "about",
            "between",
            "during",
            "after",
            "before",
            "under",
            "over",
            "into",
            "through",
            "across",
            "within",
            "without",
            "around",
            "toward",
            "towards",
            "until",
            "since",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        }
        return {entity for entity in entities if len(entity) > 2 and entity not in stop_entities}

    def _query_entities(self, query: str) -> set[str]:
        entities = {token.lower() for token in extract_entities(query)}
        entities.update(match.lower() for match in re.findall(r"\b([A-Z][a-z]+)'s\b", query))
        return self._filter_entity_tokens(entities)

    def _extract_alias_pairs(self, text: str) -> set[tuple[str, str]]:
        lowered = text.lower()
        pairs: set[tuple[str, str]] = set()
        for pattern in self.ENTITY_ALIAS_PATTERNS:
            for left, right in pattern.findall(lowered):
                normalized = self._filter_entity_tokens({left, right})
                if len(normalized) != 2:
                    continue
                first, second = tuple(sorted(normalized))
                pairs.add((first, second))
        return pairs

    def _expand_query_entities(self, agent_id: str, query_entities: set[str]) -> set[str]:
        if not query_entities:
            return set()
        alias_map: dict[str, set[str]] = {}
        for node in self.store.list_nodes(agent_id=agent_id, level=MemoryLevel.L0):
            for left, right in self._extract_alias_pairs(node.text):
                alias_map.setdefault(left, set()).add(right)
                alias_map.setdefault(right, set()).add(left)
        expanded = set(query_entities)
        queue = list(query_entities)
        while queue:
            current = queue.pop()
            for alias in alias_map.get(current, set()):
                if alias in expanded:
                    continue
                expanded.add(alias)
                queue.append(alias)
        return self._filter_entity_tokens(expanded)

    def _node_entities(self, node: MemoryNode) -> set[str]:
        entities = self._filter_entity_tokens({token.lower() for token in node.entities})
        if entities:
            return entities
        return self._filter_entity_tokens({token.lower() for token in extract_entities(node.text)})

    def _has_negated_query_entity(self, text: str, query_entities: set[str]) -> bool:
        if not query_entities:
            return False
        lowered = text.lower()
        for entity in query_entities:
            if re.search(rf"\bnot\s+(?:about|for|with)\s+{re.escape(entity)}\b", lowered):
                return True
        return False

    def _has_conflicting_named_entity(self, node: MemoryNode, query_entities: set[str]) -> bool:
        if not query_entities:
            return False
        node_entities = self._node_entities(node)
        if not node_entities:
            return False
        return bool(node_entities - query_entities)

    def _is_entity_aligned(self, node: MemoryNode, query_entities: set[str]) -> bool:
        if not query_entities:
            return True
        if self._has_negated_query_entity(node.text, query_entities):
            return False
        node_entities = self._node_entities(node)
        if node_entities & query_entities:
            return True
        lowered = node.text.lower()
        return any(re.search(rf"\b{re.escape(entity)}\b", lowered) for entity in query_entities)

    def _entity_alignment_adjustment(self, node: MemoryNode, query_entities: set[str]) -> float:
        if not query_entities:
            return 0.0
        node_entities = self._node_entities(node)
        if self._has_negated_query_entity(node.text, query_entities):
            return -0.25
        if self._is_entity_aligned(node, query_entities):
            return 0.08
        if node_entities and not (node_entities & query_entities):
            return -0.08
        return 0.0

    def _build_coverage_plan(
        self,
        query: str,
        feature_scores: dict[str, float],
        query_entities: set[str],
    ) -> CoveragePlan:
        return build_coverage_plan(
            query=query,
            feature_scores=feature_scores,
            query_entities=query_entities,
            feature_scorer=self.feature_scorer,
        )

    def _dynamic_target_leaf_count(
        self,
        *,
        leaf_count: int,
        covered: set[str],
        required_facets: set[str],
        communication_facets: set[str],
        communication_min_hits: int,
        low_confidence: bool,
        routing_expansion: bool,
        enforce_entity_thread: bool,
        query_entities: set[str],
        picked: list[CandidateScore],
        needs_polarity_balance: bool,
        needs_entity_disambiguation: bool,
        expansion_target: int,
    ) -> int:
        return dynamic_target_leaf_count(
            leaf_count=leaf_count,
            covered=covered,
            required_facets=required_facets,
            communication_facets=communication_facets,
            communication_min_hits=communication_min_hits,
            low_confidence=low_confidence,
            routing_expansion=routing_expansion,
            enforce_entity_thread=enforce_entity_thread,
            query_entities=query_entities,
            has_entity_thread_anchor=self._has_entity_thread_anchor(picked, query_entities),
            needs_polarity_balance=needs_polarity_balance,
            needs_entity_disambiguation=needs_entity_disambiguation,
            expansion_target=expansion_target,
        )

    def _needs_entity_disambiguation_support(
        self,
        *,
        query_entities: set[str],
        picked: list[CandidateScore],
        ambiguity_cue: float,
        feature_active_min: float,
        low_confidence: bool,
    ) -> bool:
        if not query_entities:
            return False
        if ambiguity_cue < feature_active_min and not low_confidence:
            return False
        leaves = [item.node for item in picked if item.node.level == MemoryLevel.L0]
        if not leaves:
            return True
        aligned_leaves = [leaf for leaf in leaves if self._is_entity_aligned(leaf, query_entities)]
        if not aligned_leaves:
            return True
        if len(aligned_leaves) == 1:
            return True
        return any(self._has_conflicting_named_entity(leaf, query_entities) for leaf in leaves)

    def _supplemental_utility_threshold(
        self,
        *,
        leaf_count: int,
        missing_required: set[str],
        communication_gap: bool,
        needs_polarity_balance: bool,
        needs_entity_disambiguation: bool,
        temporal_cue: float,
        ambiguity_cue: float,
        low_confidence: bool,
        feature_active_min: float,
    ) -> float:
        if leaf_count <= 0:
            return 0.0
        thresholds = self.feature_scorer.supplemental_thresholds
        threshold = float(thresholds.get("base_utility_threshold", 0.08))
        if missing_required:
            threshold -= float(thresholds.get("missing_required_relax", 0.02))
        if communication_gap:
            threshold -= float(thresholds.get("communication_gap_relax", 0.02))
        if needs_polarity_balance:
            threshold -= float(thresholds.get("polarity_relax", 0.02))
        if needs_entity_disambiguation:
            threshold -= float(thresholds.get("disambiguation_relax", 0.03))
        if low_confidence:
            threshold -= float(thresholds.get("low_confidence_relax", 0.01))
        temporal_only = (
            temporal_cue >= feature_active_min
            and ambiguity_cue < feature_active_min
            and not missing_required
            and not communication_gap
            and not needs_polarity_balance
            and not needs_entity_disambiguation
            and not low_confidence
        )
        if temporal_only:
            threshold += float(thresholds.get("temporal_only_penalty", 0.04))
        min_threshold = float(thresholds.get("min_utility_threshold", 0.04))
        max_threshold = float(thresholds.get("max_utility_threshold", 0.14))
        return min(max_threshold, max(min_threshold, threshold))

    def _has_entity_thread_anchor(self, picked: list[CandidateScore], query_entities: set[str]) -> bool:
        if not query_entities:
            return False
        return any(
            item.node.level == MemoryLevel.L0 and self._is_entity_aligned(item.node, query_entities)
            for item in picked
        )

    def _is_explicit_negation_query(self, query: str) -> bool:
        lowered = query.lower()
        return any(token in lowered for token in [" not ", "did not", "do not", "don't", "never"])

    def _has_negative_commitment(self, text: str) -> bool:
        lowered = text.lower()
        return bool(
            re.search(
                r"\b(?:did not|do not|don't|never)\s+(?:agree|agreed|commit|committed|promise|promised)\b",
                lowered,
            )
        )

    def _has_affirmative_commitment(self, text: str) -> bool:
        lowered = text.lower()
        if not re.search(r"\b(?:agree|agreed|commit|committed|promise|promised)\b", lowered):
            return False
        if self._has_negative_commitment(lowered):
            return False
        return True

    def _needs_negation_polarity_balance(self, query: str, picked: list[CandidateScore]) -> bool:
        if self._is_explicit_negation_query(query):
            return False
        need_negative, need_affirmative = self._missing_commitment_polarity(picked)
        return need_negative ^ need_affirmative

    def _missing_commitment_polarity(self, picked: list[CandidateScore]) -> tuple[bool, bool]:
        leaves = [item.node.text for item in picked if item.node.level == MemoryLevel.L0]
        if not leaves:
            return False, False
        has_negative = any(self._has_negative_commitment(text) for text in leaves)
        has_affirmative = any(self._has_affirmative_commitment(text) for text in leaves)
        return (not has_negative), (not has_affirmative)

    def _shares_thread_with_aligned_leaf(
        self,
        node: MemoryNode,
        picked: list[CandidateScore],
        query_entities: set[str],
    ) -> bool:
        if not query_entities:
            return True
        if self._is_entity_aligned(node, query_entities):
            return True
        aligned_leaves = [
            item.node
            for item in picked
            if item.node.level == MemoryLevel.L0 and self._is_entity_aligned(item.node, query_entities)
        ]
        if not aligned_leaves:
            return False
        aligned_parent_ids = {parent_id for leaf in aligned_leaves for parent_id in leaf.parent_ids}
        if aligned_parent_ids and set(node.parent_ids) & aligned_parent_ids:
            return True
        aligned_entities = {entity for leaf in aligned_leaves for entity in self._node_entities(leaf)}
        node_entities = self._node_entities(node)
        if aligned_entities and node_entities and (aligned_entities & node_entities):
            return True
        return False

    def _is_revision_leaf_first_query(self, query: str) -> bool:
        terms = self._query_terms(query)
        has_revision_cue = bool(terms & {"latest", "updated", "changed", "revision", "now", "current", "actually"})
        if not has_revision_cue:
            return False
        asks_timing = "when" in terms or "day" in terms or ("which" in terms and "day" in terms) or "current" in terms
        asks_current = bool(terms & {"actually", "latest", "current", "now", "currently"})
        asks_ship = bool(terms & {"ship", "shipping", "launch"})
        return asks_timing and asks_ship and asks_current

    def _leaf_satisfies_revision_slot_cues(self, query: str, leaf_text: str) -> bool:
        lowered_query = query.lower()
        lowered_leaf = leaf_text.lower()
        day_tokens = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        override_tokens = ["updated", "latest", "current", "now", "revision", "correct", "final", "instead", "actually"]
        asks_for_latest = any(token in lowered_query for token in ["latest", "current", "now", "actually"])
        asks_for_timing = "when" in lowered_query or asks_for_latest
        asks_for_ship = any(token in lowered_query for token in ["ship", "launch"])
        has_day_or_time = any(token in lowered_leaf for token in day_tokens) or "after" in lowered_leaf
        has_override_cue = any(token in lowered_leaf for token in override_tokens)
        if asks_for_ship and not any(token in lowered_leaf for token in ["ship", "launch"]):
            return False
        if asks_for_timing and not has_day_or_time:
            return False
        if asks_for_latest and not has_override_cue:
            return False
        return True

    def _select_revision_enrichment_leaf(
        self,
        query: str,
        top_leaf: CandidateScore,
        ranked_leaves: list[CandidateScore],
        token_budget: int,
        enabled: bool = True,
    ) -> CandidateScore | None:
        if not enabled:
            return None
        top_text = top_leaf.node.text.lower()
        enrichment_tokens = ["launch", "canonical", "correct", "current", "latest", "final", "date", "ship"]
        for candidate in ranked_leaves[1:5]:
            if top_leaf.node.token_count + candidate.node.token_count > token_budget:
                continue
            if candidate.score < top_leaf.score * 0.6:
                continue
            candidate_text = candidate.node.text.lower()
            if any(token in candidate_text and token not in top_text for token in enrichment_tokens):
                return candidate
        return None

    def _select_children_for_query(
        self,
        query: str,
        child_scores: list[CandidateScore],
        max_children: int,
        query_entities: set[str] | None = None,
        enforce_entity_anchor: bool = True,
        required_facets: set[str] | None = None,
    ) -> list[CandidateScore]:
        selected = self._select_children_with_coverage(
            child_scores=child_scores,
            max_children=max_children,
            coverage_fn=lambda item: self._generic_coverage_keys(query, item.node.text),
            required_facets=required_facets or set(),
        )
        if not enforce_entity_anchor:
            return selected
        return self._anchor_children_to_entities(
            selected=selected,
            ranked_children=child_scores,
            query_entities=query_entities or set(),
            max_children=max_children,
        )

    def _anchor_children_to_entities(
        self,
        selected: list[CandidateScore],
        ranked_children: list[CandidateScore],
        query_entities: set[str],
        max_children: int,
    ) -> list[CandidateScore]:
        if not query_entities or not selected:
            return selected
        if any(self._is_entity_aligned(item.node, query_entities) for item in selected):
            return selected
        anchor_candidate = next(
            (item for item in ranked_children if self._is_entity_aligned(item.node, query_entities)),
            None,
        )
        if anchor_candidate is None:
            return selected
        if anchor_candidate in selected:
            return selected
        if len(selected) < max_children:
            return [*selected, anchor_candidate]
        anchored = list(selected)
        anchored[-1] = anchor_candidate
        deduped: list[CandidateScore] = []
        seen_ids: set[str] = set()
        for item in anchored:
            if item.node.node_id in seen_ids:
                continue
            deduped.append(item)
            seen_ids.add(item.node.node_id)
        return deduped

    def _select_children_with_coverage(
        self,
        child_scores: list[CandidateScore],
        max_children: int,
        coverage_fn,
        required_facets: set[str],
    ) -> list[CandidateScore]:
        if max_children <= 0:
            return []
        selected: list[CandidateScore] = []
        covered: set[str] = set()
        for item in child_scores:
            if len(selected) >= max_children:
                break
            coverage = coverage_fn(item)
            new_coverage = coverage - covered
            required_hits = new_coverage & required_facets
            if not selected or required_hits or new_coverage:
                selected.append(item)
                covered.update(coverage)
        if len(selected) < max_children:
            for item in child_scores:
                if len(selected) >= max_children:
                    break
                if item in selected:
                    continue
                selected.append(item)
        return selected

    def _generic_coverage_keys(self, query: str, text: str) -> set[str]:
        query_terms = self._query_terms(query)
        lowered = text.lower()
        text_terms = self._query_terms(text)
        query_entities = {token.lower() for token in extract_entities(query)}
        keys: set[str] = set()
        stop_terms = {
            "the",
            "a",
            "an",
            "i",
            "me",
            "my",
            "for",
            "to",
            "of",
            "and",
            "or",
            "is",
            "are",
            "was",
            "were",
            "at",
            "in",
            "on",
            "what",
            "which",
            "how",
            "when",
            "with",
            "given",
            "based",
            "using",
        }
        for term in query_terms:
            if len(term) <= 2 or term in stop_terms:
                continue
            if term in text_terms:
                keys.add(f"term:{term}")
        for entity in query_entities:
            if entity in lowered:
                keys.add(f"entity:{entity}")
        if any(token in lowered for token in ["promise", "promised", "commit", "committed", "agree", "agreed"]):
            keys.add("facet:commitment")
        if any(token in lowered for token in ["bring", "pack", "bringing"]):
            keys.add("facet:action")
        if any(token in lowered for token in ["prefer", "preference", "likes"]):
            keys.add("facet:preference")
        if any(token in lowered for token in ["dislike", "dislikes", "hate", "hates", "avoid"]):
            keys.add("facet:avoid")
        if any(token in lowered for token in ["demo", "review", "showcase", "meeting"]):
            keys.add("facet:event")
        if any(token in lowered for token in ["should", "works best", "send", "confirm", "summarize", "in writing"]):
            keys.add("facet:strategy")
        if any(token in lowered for token in ["updated", "latest", "current", "now", "final", "revision", "ship", "launch"]):
            keys.add("facet:temporal")
        if any(token in lowered for token in ["did not", "do not", "not ", "never", "don't"]):
            keys.add("facet:negation")
        return keys
