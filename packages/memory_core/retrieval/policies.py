from __future__ import annotations

"""Retrieval policy objects and scoring helpers
Holds routing features thresholds and coverage math"""

import math
import re
from dataclasses import dataclass

from packages.memory_core.retrieval.pipeline_types import CandidateScore, QueryRoutingDecision
from packages.schemas.models import QueryMode

@dataclass(frozen=True)
class CoveragePlan:
    """Coverage constraints for supplemental selection
    Captures facet requirements communication coverage and entity threading needs"""

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
class SupplementalScoringPolicy:
    """Scoring policy for supplemental leaf utility
    Provides bonus and threshold functions used by selection loop"""

    weights: dict[str, float]
    thresholds: dict[str, float]

    def utility_bonus(
        self,
        *,
        new_coverage_count: int,
        required_hits_count: int,
        adds_communication: bool,
        provides_polarity_signal: bool,
        provides_disambiguation_signal: bool,
        is_entity_aligned: bool,
    ) -> float:
        """Compute additive bonus from coverage and alignment signals"""
        bonus = 0.0
        bonus += self.weights.get("coverage_bonus_per_key", 0.06) * new_coverage_count
        bonus += self.weights.get("required_bonus_per_key", 0.12) * required_hits_count
        if adds_communication:
            bonus += self.weights.get("communication_bonus", 0.10)
        if provides_polarity_signal:
            bonus += self.weights.get("polarity_bonus", 0.10)
        if provides_disambiguation_signal:
            bonus += self.weights.get("disambiguation_bonus", 0.10)
        if is_entity_aligned:
            bonus += self.weights.get("entity_aligned_bonus", 0.03)
        return bonus

    def utility_threshold(
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
        """Compute dynamic utility gate threshold"""
        if leaf_count <= 0:
            return 0.0
        threshold = float(self.thresholds.get("base_utility_threshold", 0.08))
        if missing_required:
            threshold -= float(self.thresholds.get("missing_required_relax", 0.02))
        if communication_gap:
            threshold -= float(self.thresholds.get("communication_gap_relax", 0.02))
        if needs_polarity_balance:
            threshold -= float(self.thresholds.get("polarity_relax", 0.02))
        if needs_entity_disambiguation:
            threshold -= float(self.thresholds.get("disambiguation_relax", 0.03))
        if low_confidence:
            threshold -= float(self.thresholds.get("low_confidence_relax", 0.01))
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
            threshold += float(self.thresholds.get("temporal_only_penalty", 0.04))
        min_threshold = float(self.thresholds.get("min_utility_threshold", 0.04))
        max_threshold = float(self.thresholds.get("max_utility_threshold", 0.14))
        return min(max_threshold, max(min_threshold, threshold))


class QueryFeatureScorer:
    """Feature scorer for query routing
    Converts text triggers and weights into normalized cues and strategy decisions"""

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
        """Normalize text for trigger matching"""
        lowered = text.lower()
        for source, target in self.CONTRACTION_MAP.items():
            lowered = re.sub(rf"\b{re.escape(source)}\b", target, lowered)
        lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _query_terms(self, query: str) -> set[str]:
        """Tokenize normalized query text"""
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
        """Score feature cues and return fired rule tags"""
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
        """Map feature scores to a routing decision"""
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

        # keep flat route only when cues are absent
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

def build_coverage_plan(
    *,
    query: str,
    feature_scores: dict[str, float],
    query_entities: set[str],
    feature_scorer: QueryFeatureScorer,
) -> CoveragePlan:
    """Build coverage plan from query intent
    Derives required facets communication minimums and entity thread enforcement"""
    terms = feature_scorer._query_terms(query)
    lowered = query.lower()
    feature_active_min = feature_scorer.thresholds.get("feature_active_min", 0.34)
    coverage_min = feature_scorer.thresholds.get("coverage_min", 0.45)
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

def dynamic_target_leaf_count(
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
    has_entity_thread_anchor: bool,
    needs_polarity_balance: bool,
    needs_entity_disambiguation: bool,
    expansion_target: int,
) -> int:
    """Compute adaptive supplemental target leaf count
    Expands only when missing facets confidence issues or disambiguation pressure remain"""
    if leaf_count <= 0:
        return 1
    target = max(2, int(expansion_target))
    missing_required = required_facets - covered
    communication_hits = len(communication_facets & covered)
    if missing_required:
        return max(leaf_count, target)
    if communication_hits < communication_min_hits:
        return max(leaf_count, target)
    if enforce_entity_thread and query_entities and not has_entity_thread_anchor:
        return max(leaf_count, target)
    if needs_polarity_balance:
        return max(leaf_count, target)
    if needs_entity_disambiguation:
        return max(leaf_count, target)
    if low_confidence:
        return max(leaf_count, target)
    if routing_expansion:
        return leaf_count
    return leaf_count
