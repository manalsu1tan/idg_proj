from __future__ import annotations

import json
import math
import re
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from packages.memory_core.model_components import ModelBackedSummarizer, ModelBackedVerifier, build_model_client
from packages.memory_core.settings import Settings
from packages.memory_core.storage import Database, MemoryStore
from packages.memory_core.utils import (
    extract_entities,
    jaccard_similarity,
    normalize_importance,
    pseudo_embedding,
    recency_score,
    relevance_score,
    source_hash,
    token_count,
    unique_topics,
)
from packages.schemas.models import (
    AgentTreeResponse,
    BuildSummariesRequest,
    CreatedBy,
    EvalRunResult,
    MemoryLevel,
    MemoryNode,
    NodeProvenance,
    NodeType,
    QualityStatus,
    QueryMode,
    RefreshRequest,
    RetrievalDiagnostics,
    RetrievalTrace,
    RetrievalTraceEntry,
    RetrieveResponse,
    RetrievedNode,
    RetrievalMetadata,
    TimelineResponse,
    dump_model,
)


@dataclass
class CandidateScore:
    node: MemoryNode
    score: float
    relevance: float
    recency: float


@dataclass(frozen=True)
class CoveragePlan:
    min_leaf_count: int
    required_facets: tuple[str, ...]
    communication_facets: tuple[str, ...]
    communication_min_hits: int
    enforce_entity_thread: bool

    @property
    def requires_multi_leaf(self) -> bool:
        return self.min_leaf_count > 1

    @property
    def has_required_facets(self) -> bool:
        return bool(self.required_facets)


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


class QueryFeatureScorer:
    CONTRACTION_MAP: dict[str, str] = {
        "don't": "do not",
        "dont": "do not",
        "didn't": "did not",
        "didnt": "did not",
        "can't": "cannot",
        "cant": "cannot",
        "won't": "will not",
        "wont": "will not",
        "i'd": "i would",
        "i'll": "i will",
        "i'm": "i am",
    }

    FEATURE_KEYS: tuple[str, ...] = (
        "temporal_cue",
        "conflict_cue",
        "composition_cue",
        "negation_cue",
        "entity_ambiguity_cue",
    )

    def __init__(self, policy: dict) -> None:
        self.policy = policy
        self.feature_triggers: dict[str, list[str]] = {
            key: [self._normalize_text(str(item)) for item in value if self._normalize_text(str(item))]
            for key, value in (policy.get("feature_triggers", {}) or {}).items()
            if isinstance(value, list)
        }
        self.feature_norms: dict[str, float] = {
            key: float(value)
            for key, value in (policy.get("feature_norms", {}) or {}).items()
            if isinstance(value, (int, float))
        }
        self.feature_weights: dict[str, float] = {
            key: float(value)
            for key, value in (policy.get("feature_weights", {}) or {}).items()
            if isinstance(value, (int, float))
        }
        self.thresholds: dict[str, float] = {
            key: float(value)
            for key, value in (policy.get("strategy_thresholds", {}) or {}).items()
            if isinstance(value, (int, float))
        }
        self.resolver_thresholds: dict[str, float] = {
            key: float(value)
            for key, value in (policy.get("resolver_thresholds", {}) or {}).items()
            if isinstance(value, (int, float))
        }
        self.supplemental_weights: dict[str, float] = {
            key: float(value)
            for key, value in (policy.get("supplemental_weights", {}) or {}).items()
            if isinstance(value, (int, float))
        }
        self.supplemental_thresholds: dict[str, float] = {
            key: float(value)
            for key, value in (policy.get("supplemental_thresholds", {}) or {}).items()
            if isinstance(value, (int, float))
        }
        for feature in self.FEATURE_KEYS:
            self.feature_triggers.setdefault(feature, [])
            self.feature_norms.setdefault(feature, 2.0)
            self.feature_weights.setdefault(feature, 1.0)
        self.thresholds.setdefault("flat_top1_max", 0.32)
        self.thresholds.setdefault("revision_leaf_min", 0.45)
        self.thresholds.setdefault("coverage_min", 0.45)
        self.thresholds.setdefault("hierarchy_expand_min", 0.48)
        self.thresholds.setdefault("multi_branch_min", 0.65)
        self.thresholds.setdefault("feature_active_min", 0.34)
        self.resolver_thresholds.setdefault("low_confidence_margin", 0.08)
        self.resolver_thresholds.setdefault("disambiguation_close_margin", 0.08)
        self.resolver_thresholds.setdefault("competing_person_score_ratio", 0.55)
        self.resolver_thresholds.setdefault("competing_person_score_gap", 0.25)
        self.resolver_thresholds.setdefault("competing_person_window", 8.0)
        self.resolver_thresholds.setdefault("expansion_branch_target", 2.0)
        self.supplemental_weights.setdefault("coverage_bonus_per_key", 0.06)
        self.supplemental_weights.setdefault("required_bonus_per_key", 0.12)
        self.supplemental_weights.setdefault("communication_bonus", 0.10)
        self.supplemental_weights.setdefault("polarity_bonus", 0.10)
        self.supplemental_weights.setdefault("disambiguation_bonus", 0.10)
        self.supplemental_weights.setdefault("entity_aligned_bonus", 0.03)
        self.supplemental_thresholds.setdefault("base_utility_threshold", 0.08)
        self.supplemental_thresholds.setdefault("missing_required_relax", 0.02)
        self.supplemental_thresholds.setdefault("communication_gap_relax", 0.02)
        self.supplemental_thresholds.setdefault("polarity_relax", 0.02)
        self.supplemental_thresholds.setdefault("disambiguation_relax", 0.03)
        self.supplemental_thresholds.setdefault("low_confidence_relax", 0.01)
        self.supplemental_thresholds.setdefault("temporal_only_penalty", 0.04)
        self.supplemental_thresholds.setdefault("min_utility_threshold", 0.04)
        self.supplemental_thresholds.setdefault("max_utility_threshold", 0.14)

    def _normalize_text(self, text: str) -> str:
        lowered = text.lower()
        for source, target in self.CONTRACTION_MAP.items():
            lowered = re.sub(rf"\b{re.escape(source)}\b", target, lowered)
        lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _query_terms(self, query: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", self._normalize_text(query)))

    def _edit_distance_le_one(self, source: str, target: str) -> bool:
        if source == target:
            return True
        len_source = len(source)
        len_target = len(target)
        if abs(len_source - len_target) > 1:
            return False
        if len_source == len_target:
            mismatches = sum(1 for index in range(len_source) if source[index] != target[index])
            return mismatches <= 1
        if len_source < len_target:
            source, target = target, source
            len_source, len_target = len_target, len_source
        i = 0
        j = 0
        mismatch_seen = False
        while i < len_source and j < len_target:
            if source[i] == target[j]:
                i += 1
                j += 1
                continue
            if mismatch_seen:
                return False
            mismatch_seen = True
            i += 1
        return True

    def _token_match(self, trigger_token: str, query_terms: set[str], query_term_list: list[str]) -> bool:
        if trigger_token in query_terms:
            return True
        if len(trigger_token) < 6:
            return False
        for term in query_term_list:
            if len(term) < 6:
                continue
            if trigger_token[:2] != term[:2]:
                continue
            if trigger_token[-1] != term[-1]:
                continue
            if self._edit_distance_le_one(trigger_token, term):
                return True
        return False

    def score(self, query: str) -> tuple[dict[str, float], list[str]]:
        normalized_query = self._normalize_text(query)
        terms = self._query_terms(query)
        query_term_list = list(terms)
        ambiguity_intent_terms = {
            "alias",
            "pronoun",
            "whom",
            "who exactly",
            "which person",
            "same name",
            "different person",
        }
        disambiguation_intent = any(term in normalized_query for term in ambiguity_intent_terms)
        pronoun_triggers = {"he", "she", "they", "him", "her"}
        scores: dict[str, float] = {}
        fired_rules: list[str] = []
        for feature in self.FEATURE_KEYS:
            triggers = self.feature_triggers.get(feature, [])
            matched: list[str] = []
            matched_weight = 0.0
            for trigger in triggers:
                if feature == "entity_ambiguity_cue" and trigger in pronoun_triggers and not disambiguation_intent:
                    continue
                if " " not in trigger:
                    if self._token_match(trigger, terms, query_term_list):
                        matched.append(trigger)
                        matched_weight += 1.0
                    continue
                if trigger in normalized_query:
                    matched.append(trigger)
                    matched_weight += 1.25 if len(trigger.split()) >= 3 else 1.1
                    continue
                trigger_tokens = [token for token in trigger.split() if token]
                if len(trigger_tokens) >= 2 and all(
                    self._token_match(token, terms, query_term_list) for token in trigger_tokens
                ):
                    matched.append(trigger)
                    matched_weight += 1.25 if len(trigger_tokens) >= 3 else 1.1
            for trigger in matched:
                fired_rules.append(f"{feature}:{trigger}")
            norm = max(self.feature_norms.get(feature, 2.0), 1.0)
            scores[feature] = min(1.0, matched_weight / norm)
        return scores, fired_rules

    def decide(self, query: str, *, mode: QueryMode, branch_limit: int) -> QueryRoutingDecision:
        feature_scores, fired_rules = self.score(query)
        terms = self._query_terms(query)
        weighted_total = 0.0
        weight_sum = 0.0
        for feature in self.FEATURE_KEYS:
            weight = self.feature_weights.get(feature, 1.0)
            weighted_total += feature_scores.get(feature, 0.0) * weight
            weight_sum += weight
        hierarchical_score = weighted_total / max(weight_sum, 1.0)
        if mode != QueryMode.BALANCED:
            return QueryRoutingDecision(
                strategy="mode_override",
                reason="Mode is not balanced; strategy is controlled by request mode.",
                feature_scores=feature_scores,
                fired_rules=fired_rules,
                hierarchical_score=hierarchical_score,
                branch_limit_override=max(1, branch_limit),
                enable_coverage_expansion=False,
                enable_revision_enrichment=False,
            )

        temporal = feature_scores["temporal_cue"]
        conflict = feature_scores["conflict_cue"]
        composition = feature_scores["composition_cue"]
        negation = feature_scores["negation_cue"]
        ambiguity = feature_scores["entity_ambiguity_cue"]
        coverage = max(composition, negation)

        flat_top1_max = self.thresholds["flat_top1_max"]
        revision_leaf_min = self.thresholds["revision_leaf_min"]
        coverage_min = self.thresholds["coverage_min"]
        hierarchy_expand_min = self.thresholds["hierarchy_expand_min"]
        multi_branch_min = self.thresholds["multi_branch_min"]
        correction_focus = bool(terms & {"actually", "now", "current", "correct", "updated", "changed", "revision"})

        # Keep flat-only routing for genuinely cue-free prompts.
        if hierarchical_score <= flat_top1_max and not fired_rules:
            return QueryRoutingDecision(
                strategy="flat_top1",
                reason=f"Hierarchical score {hierarchical_score:.2f} is below flat threshold {flat_top1_max:.2f}.",
                feature_scores=feature_scores,
                fired_rules=fired_rules,
                hierarchical_score=hierarchical_score,
                branch_limit_override=1,
                enable_coverage_expansion=False,
                enable_revision_enrichment=False,
            )

        if temporal >= revision_leaf_min and coverage < coverage_min and conflict < hierarchy_expand_min:
            return QueryRoutingDecision(
                strategy="revision_leaf_first",
                reason="Temporal cue dominates while coverage/conflict cues are low.",
                feature_scores=feature_scores,
                fired_rules=fired_rules,
                hierarchical_score=hierarchical_score,
                branch_limit_override=1,
                enable_coverage_expansion=False,
                enable_revision_enrichment=correction_focus,
            )

        should_expand = (
            hierarchical_score >= hierarchy_expand_min
            or coverage >= coverage_min
            or conflict >= hierarchy_expand_min
            or ambiguity >= hierarchy_expand_min
        )
        if should_expand:
            widest = max(temporal, conflict, coverage, ambiguity)
            branch_override = 2 if widest >= multi_branch_min else 1
            return QueryRoutingDecision(
                strategy="hierarchy_expand",
                reason="Feature score indicates multi-fact or ambiguity pressure.",
                feature_scores=feature_scores,
                fired_rules=fired_rules,
                hierarchical_score=hierarchical_score,
                branch_limit_override=branch_override,
                enable_coverage_expansion=coverage >= coverage_min,
                enable_revision_enrichment=temporal >= revision_leaf_min,
            )

        return QueryRoutingDecision(
            strategy="hierarchy_single",
            reason="Moderate feature score; use conservative hierarchy strategy.",
            feature_scores=feature_scores,
            fired_rules=fired_rules,
            hierarchical_score=hierarchical_score,
            branch_limit_override=1,
            enable_coverage_expansion=False,
            enable_revision_enrichment=temporal >= revision_leaf_min,
        )


class RefreshPolicy:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def mark_stale(self, request: RefreshRequest) -> list[MemoryNode]:
        parents = self.store.parent_nodes(request.changed_node_ids)
        stale_ids = [node.node_id for node in parents]
        return self.store.mark_stale(stale_ids)


class FlatRetriever:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        token_budget: int,
        limit: int = 8,
    ) -> list[CandidateScore]:
        nodes = self.store.list_nodes(agent_id=agent_id, level=MemoryLevel.L0)
        candidates: list[CandidateScore] = []
        for node in nodes:
            rel = relevance_score(query, node.text)
            rec = recency_score(query_time, node.timestamp_end)
            imp = normalize_importance(node.importance_score)
            score = statistics.fmean([rel, rec, imp])
            candidates.append(CandidateScore(node=node, score=score, relevance=rel, recency=rec))
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        picked: list[CandidateScore] = []
        consumed = 0
        for item in ranked:
            if len(picked) >= limit:
                break
            if consumed + item.node.token_count > token_budget:
                continue
            consumed += item.node.token_count
            self.store.mark_accessed(item.node.node_id, item.relevance, item.recency, query_time)
            picked.append(item)
        return picked


class TreeBuilder:
    def __init__(
        self,
        store: MemoryStore,
        summarizer: ModelBackedSummarizer,
        verifier: ModelBackedVerifier,
        settings: Settings,
    ) -> None:
        self.store = store
        self.summarizer = summarizer
        self.verifier = verifier
        self.settings = settings

    def build_level(self, request: BuildSummariesRequest) -> list[MemoryNode]:
        if request.source_level != MemoryLevel.L0 or request.target_level != MemoryLevel.L1:
            raise ValueError("The MVP only supports L0 to L1 summary construction.")
        nodes = self.store.list_nodes(agent_id=request.agent_id, level=request.source_level)
        clusters = self._cluster_nodes(nodes)
        built: list[MemoryNode] = []
        for cluster in clusters:
            if not self._should_summarize_cluster(cluster):
                continue
            support_hash = source_hash([item.node_id for item in cluster] + [item.text for item in cluster])
            existing = self.store.existing_summary(
                agent_id=request.agent_id,
                target_level=request.target_level,
                support_hash=support_hash,
            )
            if existing is not None:
                built.append(existing)
                continue
            summary_result, summary_trace = self.summarizer.generate(request.agent_id, cluster)
            summary_node = MemoryNode(
                node_id=str(uuid.uuid4()),
                agent_id=request.agent_id,
                level=request.target_level,
                node_type=NodeType.SUMMARY,
                text=summary_result.text,
                timestamp_start=cluster[0].timestamp_start,
                timestamp_end=cluster[-1].timestamp_end,
                parent_ids=[],
                child_ids=[node.node_id for node in cluster],
                support_ids=[node.node_id for node in cluster],
                embedding=pseudo_embedding(summary_result.text),
                importance_score=max(node.importance_score for node in cluster),
                retrieval_metadata=RetrievalMetadata(),
                entities=summary_result.entities or extract_entities(summary_result.text),
                topics=summary_result.topics or unique_topics(summary_result.text),
                commitments=summary_result.commitments,
                revisions=summary_result.revisions,
                preferences=summary_result.preferences,
                relationship_guidance=summary_result.relationship_guidance,
                self_model_updates=summary_result.self_model_updates,
                version=self.store.next_version(request.agent_id, request.target_level, support_hash),
                stale_flag=False,
                summary_policy_id="rolling-window-v1",
                quality_status=QualityStatus.PENDING,
                quality_scores={},
                token_count=token_count(summary_result.text),
                source_hash=support_hash,
                created_by=CreatedBy.SUMMARIZER,
                prompt_version=summary_result.prompt_version,
                model_version=summary_result.model_version,
            )
            summary_trace.node_id = summary_node.node_id
            self.store.write_model_trace(summary_trace)
            verification_result, verification_trace = self.verifier.verify(request.agent_id, summary_node, cluster)
            summary_node.quality_status = verification_result.quality_status
            summary_node.quality_scores = verification_result.scores
            verification_trace.node_id = summary_node.node_id
            self.store.write_model_trace(verification_trace)
            if summary_node.quality_status == QualityStatus.CONTRADICTED:
                continue
            self.store.upsert_node(summary_node)
            for child in cluster:
                if summary_node.node_id not in child.parent_ids:
                    child.parent_ids.append(summary_node.node_id)
                    self.store.upsert_node(child)
            built.append(summary_node)
        return built

    def _should_summarize_cluster(self, cluster: list[MemoryNode]) -> bool:
        if len(cluster) >= 2:
            return True
        if not cluster:
            return False
        node = cluster[0]
        return node.importance_score >= 0.85 or self._contains_revision_signal(node.text)

    def _contains_revision_signal(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            token in lowered
            for token in ["updated", "changed", "now", "current", "latest", "revision", "correct", "obsolete", "instead"]
        )

    def _cluster_nodes(self, nodes: list[MemoryNode]) -> list[list[MemoryNode]]:
        if not nodes:
            return []
        clusters: list[list[MemoryNode]] = []
        current: list[MemoryNode] = [nodes[0]]
        for node in nodes[1:]:
            prev = current[-1]
            within_window = node.timestamp_start - prev.timestamp_end <= timedelta(hours=self.settings.time_window_hours)
            semantically_related = (
                jaccard_similarity(node.text, " ".join(item.text for item in current))
                >= self.settings.cluster_similarity_threshold
            )
            shared_topic = bool(set(node.topics) & {topic for item in current for topic in item.topics})
            shared_entity = bool(set(node.entities) & {entity for item in current for entity in item.entities})
            important_context = max(item.importance_score for item in current + [node]) >= 0.8 and node.importance_score >= 0.6
            if within_window and (semantically_related or shared_topic or shared_entity or important_context):
                current.append(node)
            else:
                clusters.append(current)
                current = [node]
        clusters.append(current)
        return clusters


class HierarchicalRetriever:
    ENTITY_ALIAS_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\b([a-z][a-z]+)\s*\((?:aka|a\.k\.a\.|also known as|goes by|called)\s+([a-z][a-z]+)\s*\)"),
        re.compile(r"\b([a-z][a-z]+)\s+(?:aka|a\.k\.a\.|also known as|goes by|called)\s+([a-z][a-z]+)\b"),
    )

    def __init__(self, store: MemoryStore, flat_retriever: FlatRetriever, settings: Settings) -> None:
        self.store = store
        self.flat_retriever = flat_retriever
        self.settings = settings
        self.feature_scorer = QueryFeatureScorer(settings.query_routing_policy)

    def retrieve(
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
        terms = self._query_terms(query)
        lowered = query.lower()
        feature_active_min = self.feature_scorer.thresholds.get("feature_active_min", 0.34)
        coverage_min = self.feature_scorer.thresholds.get("coverage_min", 0.45)
        composition_cue = feature_scores.get("composition_cue", 0.0)
        negation_cue = feature_scores.get("negation_cue", 0.0)
        conflict_cue = feature_scores.get("conflict_cue", 0.0)
        temporal_cue = feature_scores.get("temporal_cue", 0.0)
        ambiguity_cue = feature_scores.get("entity_ambiguity_cue", 0.0)

        required_facets: set[str] = set()
        communication_facets = ("facet:preference", "facet:avoid", "facet:strategy")
        communication_intent = bool(
            terms & {"communicate", "communication", "message", "talk", "approach", "respond", "guidance"}
        ) or "how should" in lowered
        if communication_intent:
            required_facets.add("facet:strategy")
        if terms & {"prefer", "preference", "preferences", "like", "likes"}:
            required_facets.add("facet:preference")
        if terms & {"dislike", "dislikes", "avoid", "avoids", "hate", "hates"}:
            required_facets.add("facet:avoid")
        if terms & {"commit", "committed", "commitment", "promise", "promised", "agreed", "agree"}:
            required_facets.add("facet:commitment")
        if terms & {"bring", "bringing", "item", "pack"}:
            required_facets.add("facet:action")
        if terms & {"demo", "review", "showcase", "meeting"}:
            required_facets.add("facet:event")
        if (
            query_entities
            and terms & {"bring", "bringing", "item", "pack"}
            and terms & {"commit", "committed", "commitment", "promise", "promised", "agree", "agreed"}
        ):
            required_facets.add("facet:event")
        if negation_cue >= feature_active_min or terms & {"not", "never"}:
            required_facets.add("facet:negation")
        if temporal_cue >= feature_active_min and terms & {"when", "latest", "current", "now"}:
            required_facets.add("facet:temporal")

        communication_min_hits = 2 if communication_intent else 0
        # Tightening: start with one leaf, then raise target only after observing first-leaf coverage.
        min_leaf_count = 1

        enforce_entity_thread = bool(query_entities) and (
            max(composition_cue, negation_cue) >= coverage_min
            or ambiguity_cue >= feature_active_min
            or composition_cue >= feature_active_min
            or conflict_cue >= feature_active_min
        )
        return CoveragePlan(
            min_leaf_count=min_leaf_count,
            required_facets=tuple(sorted(required_facets)),
            communication_facets=communication_facets,
            communication_min_hits=communication_min_hits,
            enforce_entity_thread=enforce_entity_thread,
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
        if leaf_count <= 0:
            return 1
        target = max(2, int(expansion_target))
        missing_required = required_facets - covered
        communication_hits = len(communication_facets & covered)
        if missing_required:
            return max(leaf_count, target)
        if communication_hits < communication_min_hits:
            return max(leaf_count, target)
        if enforce_entity_thread and query_entities and not self._has_entity_thread_anchor(picked, query_entities):
            return max(leaf_count, target)
        if needs_polarity_balance:
            return max(leaf_count, target)
        if needs_entity_disambiguation:
            return max(leaf_count, target)
        if low_confidence:
            return max(leaf_count, target)
        # If routing asked for coverage expansion but coverage is already satisfied with high confidence, do not expand.
        if routing_expansion:
            return leaf_count
        return leaf_count

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

class ContextPacker:
    def pack(self, query: str, candidates: list[CandidateScore], token_budget: int) -> str:
        lines = [f"Query: {query}", "Context:"]
        consumed = token_count(query)
        packed_texts: list[str] = []
        seen_nodes: set[str] = set()
        for candidate in candidates:
            if candidate.node.node_id in seen_nodes:
                continue
            overlap = max((jaccard_similarity(candidate.node.text, existing) for existing in packed_texts), default=0.0)
            if overlap >= 0.72:
                continue
            snippet = f"[{candidate.node.level.value}/{candidate.node.node_type.value}] {candidate.node.text}"
            snippet_tokens = token_count(snippet)
            if consumed + snippet_tokens > token_budget:
                continue
            lines.append(snippet)
            consumed += snippet_tokens
            seen_nodes.add(candidate.node.node_id)
            packed_texts.append(candidate.node.text)
        return "\n".join(lines)


def build_retrieval_diagnostics(
    candidates: list[CandidateScore],
    trace_entries: list[RetrievalTraceEntry],
    packed_context: str,
    routing_attribution: dict[str, object] | None = None,
) -> RetrievalDiagnostics:
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
        routing_strategy=str((routing_attribution or {}).get("routing_strategy")) if routing_attribution else None,
        query_feature_scores=dict((routing_attribution or {}).get("query_feature_scores", {})) if routing_attribution else {},
        fired_rules=[str(item) for item in (routing_attribution or {}).get("fired_rules", [])],
    )


class AgentLoopAdapter:
    def __init__(self, services: "MemoryService") -> None:
        self.services = services

    def observe(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.5) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.EPISODE)

    def reflect(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.7) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.REFLECTION)

    def plan(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.8) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.PLAN)


class MemoryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.database_url)
        self.store = MemoryStore(self.db, settings.prompt_version, settings.model_version)
        if settings.auto_create_schema:
            self.store.ensure_schema()
        model_client, provider = build_model_client(settings)
        self.summarizer = ModelBackedSummarizer(model_client, provider, settings)
        self.verifier = ModelBackedVerifier(model_client, provider, settings)
        self.refresh_policy = RefreshPolicy(self.store)
        self.flat_retriever = FlatRetriever(self.store)
        self.tree_builder = TreeBuilder(self.store, self.summarizer, self.verifier, settings)
        self.hierarchical_retriever = HierarchicalRetriever(self.store, self.flat_retriever, settings)
        self.context_packer = ContextPacker()
        self.agent_loop = AgentLoopAdapter(self)

    def build_summaries(self, request: BuildSummariesRequest) -> list[MemoryNode]:
        return self.tree_builder.build_level(request)

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        branch_limit: int,
    ) -> RetrieveResponse:
        retrieved, depth, trace_entries, routing_attribution = self.hierarchical_retriever.retrieve(
            agent_id=agent_id,
            query=query,
            query_time=query_time,
            mode=mode,
            token_budget=token_budget,
            branch_limit=branch_limit,
        )
        packed = self.context_packer.pack(query, retrieved, token_budget)
        diagnostics = build_retrieval_diagnostics(retrieved, trace_entries, packed, routing_attribution=routing_attribution)
        trace = RetrievalTrace(
            trace_id=str(uuid.uuid4()),
            agent_id=agent_id,
            query=query,
            mode=mode,
            token_budget=token_budget,
            retrieval_depth=depth,
            created_at=datetime.utcnow(),
            entries=trace_entries,
            diagnostics=diagnostics,
        )
        self.store.write_retrieval_trace(trace)
        return RetrieveResponse(
            query=query,
            mode=mode,
            token_budget=token_budget,
            retrieved_nodes=[
                RetrievedNode(
                    node=item.node,
                    score=item.score,
                    branch_root_id=item.node.parent_ids[0] if item.node.parent_ids else None,
                    relevance_score=item.relevance,
                    recency_score=item.recency,
                    importance_score=item.node.importance_score,
                    selected_as=next((entry.selected_as for entry in trace_entries if entry.node_id == item.node.node_id), None),
                    selection_reason=next(
                        (entry.selection_reason for entry in trace_entries if entry.node_id == item.node.node_id),
                        None,
                    ),
                )
                for item in retrieved
            ],
            packed_context=packed,
            retrieval_depth=depth,
            trace_id=trace.trace_id,
            trace_entries=trace_entries,
            diagnostics=diagnostics,
        )

    def retrieve_flat(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        token_budget: int,
        branch_limit: int,
    ) -> RetrieveResponse:
        retrieved = self.flat_retriever.retrieve(agent_id, query, query_time, token_budget, limit=branch_limit)
        packed = self.context_packer.pack(query, retrieved, token_budget)
        trace_entries = [
            RetrievalTraceEntry(
                node_id=item.node.node_id,
                level=item.node.level,
                node_type=item.node.node_type,
                score=item.score,
                relevance_score=item.relevance,
                recency_score=item.recency,
                importance_score=item.node.importance_score,
                branch_root_id=None,
                selected_as="flat_memory",
                selection_reason="Baseline flat retrieval.",
            )
            for item in retrieved
        ]
        diagnostics = build_retrieval_diagnostics(retrieved, trace_entries, packed)
        trace = RetrievalTrace(
            trace_id=str(uuid.uuid4()),
            agent_id=agent_id,
            query=query,
            mode=QueryMode.BALANCED,
            token_budget=token_budget,
            retrieval_depth=1 if retrieved else 0,
            created_at=datetime.utcnow(),
            entries=trace_entries,
            diagnostics=diagnostics,
        )
        self.store.write_retrieval_trace(trace)
        return RetrieveResponse(
            query=query,
            mode=QueryMode.BALANCED,
            token_budget=token_budget,
            retrieved_nodes=[
                RetrievedNode(
                    node=item.node,
                    score=item.score,
                    relevance_score=item.relevance,
                    recency_score=item.recency,
                    importance_score=item.node.importance_score,
                    selected_as="flat_memory",
                    selection_reason="Baseline flat retrieval.",
                )
                for item in retrieved
            ],
            packed_context=packed,
            retrieval_depth=1 if retrieved else 0,
            trace_id=trace.trace_id,
            trace_entries=trace_entries,
            diagnostics=diagnostics,
        )

    def refresh(self, request: RefreshRequest) -> list[MemoryNode]:
        return self.refresh_policy.mark_stale(request)

    def node_provenance(self, node_id: str) -> NodeProvenance:
        root = self.store.get_node(node_id)
        if root is None:
            raise KeyError(node_id)
        ancestors, descendants, supports = self.store.node_provenance(node_id)
        return NodeProvenance(root=root, ancestors=ancestors, descendants=descendants, supports=supports)

    def timeline(self, agent_id: str) -> TimelineResponse:
        return TimelineResponse(agent_id=agent_id, nodes=self.store.list_nodes(agent_id=agent_id, include_stale=True))

    def agent_tree(self, agent_id: str) -> AgentTreeResponse:
        return self.store.agent_tree(agent_id)

    def retrieval_traces(self, agent_id: str | None = None, limit: int = 20) -> list[RetrievalTrace]:
        return self.store.list_retrieval_traces(agent_id=agent_id, limit=limit)

    def model_traces(self, agent_id: str | None = None, limit: int = 20):
        return self.store.list_model_traces(agent_id=agent_id, limit=limit)

    def eval_runs(self) -> list[dict]:
        return self.store.list_eval_runs()

    def record_eval(self, result: EvalRunResult) -> None:
        self.store.write_eval_run(result.scenario_name, json.dumps(dump_model(result), default=str))
