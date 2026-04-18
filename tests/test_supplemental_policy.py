from __future__ import annotations

"""Test module overview for test supplemental policy
Covers behavior and regression checks"""

import pytest

from packages.memory_core.retrieval.policies import SupplementalScoringPolicy


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (
            {
                "new_coverage_count": 0,
                "required_hits_count": 0,
                "adds_communication": False,
                "provides_polarity_signal": False,
                "provides_disambiguation_signal": False,
                "is_entity_aligned": False,
            },
            0.0,
        ),
        (
            {
                "new_coverage_count": 2,
                "required_hits_count": 1,
                "adds_communication": True,
                "provides_polarity_signal": False,
                "provides_disambiguation_signal": False,
                "is_entity_aligned": False,
            },
            0.34,
        ),
        (
            {
                "new_coverage_count": 1,
                "required_hits_count": 1,
                "adds_communication": True,
                "provides_polarity_signal": True,
                "provides_disambiguation_signal": True,
                "is_entity_aligned": True,
            },
            0.51,
        ),
    ],
)
def test_supplemental_utility_bonus_table(params: dict[str, object], expected: float) -> None:
    policy = SupplementalScoringPolicy(
        weights={
            "coverage_bonus_per_key": 0.06,
            "required_bonus_per_key": 0.12,
            "communication_bonus": 0.10,
            "polarity_bonus": 0.10,
            "disambiguation_bonus": 0.10,
            "entity_aligned_bonus": 0.03,
        },
        thresholds={},
    )
    assert policy.utility_bonus(**params) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (
            {
                "leaf_count": 0,
                "missing_required": set(),
                "communication_gap": False,
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "temporal_cue": 0.0,
                "ambiguity_cue": 0.0,
                "low_confidence": False,
                "feature_active_min": 0.34,
            },
            0.0,
        ),
        (
            {
                "leaf_count": 1,
                "missing_required": set(),
                "communication_gap": False,
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "temporal_cue": 0.10,
                "ambiguity_cue": 0.10,
                "low_confidence": False,
                "feature_active_min": 0.34,
            },
            0.08,
        ),
        (
            {
                "leaf_count": 1,
                "missing_required": {"facet:commitment"},
                "communication_gap": False,
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "temporal_cue": 0.10,
                "ambiguity_cue": 0.10,
                "low_confidence": True,
                "feature_active_min": 0.34,
            },
            0.05,
        ),
        (
            {
                "leaf_count": 1,
                "missing_required": set(),
                "communication_gap": False,
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "temporal_cue": 0.50,
                "ambiguity_cue": 0.10,
                "low_confidence": False,
                "feature_active_min": 0.34,
            },
            0.12,
        ),
        (
            {
                "leaf_count": 2,
                "missing_required": {"facet:commitment"},
                "communication_gap": True,
                "needs_polarity_balance": True,
                "needs_entity_disambiguation": True,
                "temporal_cue": 0.10,
                "ambiguity_cue": 0.10,
                "low_confidence": True,
                "feature_active_min": 0.34,
            },
            0.04,
        ),
    ],
)
def test_supplemental_utility_threshold_table(params: dict[str, object], expected: float) -> None:
    policy = SupplementalScoringPolicy(
        weights={},
        thresholds={
            "base_utility_threshold": 0.08,
            "missing_required_relax": 0.02,
            "communication_gap_relax": 0.02,
            "polarity_relax": 0.02,
            "disambiguation_relax": 0.03,
            "low_confidence_relax": 0.01,
            "temporal_only_penalty": 0.04,
            "min_utility_threshold": 0.04,
            "max_utility_threshold": 0.14,
        },
    )
    assert policy.utility_threshold(**params) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("params", "anchor", "expected"),
    [
        (
            {
                "leaf_count": 0,
                "min_leaf_count": 1,
                "covered": set(),
                "required_facets": {"facet:commitment"},
                "communication_facets": set(),
                "communication_min_hits": 0,
                "low_confidence": False,
                "routing_expansion": False,
                "enforce_entity_thread": False,
                "query_entities": set(),
                "picked": [],
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "expansion_target": 2,
            },
            False,
            1,
        ),
        (
            {
                "leaf_count": 1,
                "min_leaf_count": 1,
                "covered": set(),
                "required_facets": {"facet:commitment"},
                "communication_facets": set(),
                "communication_min_hits": 0,
                "low_confidence": False,
                "routing_expansion": False,
                "enforce_entity_thread": False,
                "query_entities": set(),
                "picked": [],
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "expansion_target": 2,
            },
            False,
            2,
        ),
        (
            {
                "leaf_count": 1,
                "covered": set(),
                "required_facets": set(),
                "communication_facets": {"facet:communication"},
                "communication_min_hits": 1,
                "min_leaf_count": 1,
                "low_confidence": False,
                "routing_expansion": False,
                "enforce_entity_thread": False,
                "query_entities": set(),
                "picked": [],
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "expansion_target": 2,
            },
            False,
            2,
        ),
        (
            {
                "leaf_count": 2,
                "min_leaf_count": 1,
                "covered": {"facet:communication"},
                "required_facets": set(),
                "communication_facets": {"facet:communication"},
                "communication_min_hits": 1,
                "low_confidence": False,
                "routing_expansion": True,
                "enforce_entity_thread": False,
                "query_entities": set(),
                "picked": [],
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "expansion_target": 3,
            },
            False,
            2,
        ),
        (
            {
                "leaf_count": 1,
                "min_leaf_count": 1,
                "covered": {"facet:communication"},
                "required_facets": set(),
                "communication_facets": {"facet:communication"},
                "communication_min_hits": 1,
                "low_confidence": False,
                "routing_expansion": False,
                "enforce_entity_thread": True,
                "query_entities": {"maria"},
                "picked": [],
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "expansion_target": 2,
            },
            False,
            2,
        ),
        (
            {
                "leaf_count": 1,
                "min_leaf_count": 1,
                "covered": {"facet:communication"},
                "required_facets": set(),
                "communication_facets": {"facet:communication"},
                "communication_min_hits": 1,
                "low_confidence": False,
                "routing_expansion": False,
                "enforce_entity_thread": True,
                "query_entities": {"maria"},
                "picked": [],
                "needs_polarity_balance": False,
                "needs_entity_disambiguation": False,
                "expansion_target": 2,
            },
            True,
            1,
        ),
    ],
)
def test_dynamic_target_leaf_count_coverage_gating_table(
    memory_service,
    monkeypatch,
    params: dict[str, object],
    anchor: bool,
    expected: int,
) -> None:
    retriever = memory_service.hierarchical_retriever
    monkeypatch.setattr(retriever, "_has_entity_thread_anchor", lambda picked, query_entities: anchor)
    assert retriever._dynamic_target_leaf_count(**params) == expected
