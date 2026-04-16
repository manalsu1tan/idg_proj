from __future__ import annotations

"""Test module overview for test evals
Covers behavior and regression checks"""

from packages.evals.runner import run_scenario, run_selected
from packages.evals.scenarios import (
    QUICK_SCENARIO_FAMILIES,
    SCENARIO_BUILDERS,
    DEFAULT_SCENARIO_SEEDS,
    QUERY_PARAPHRASE_STYLES,
    all_scenarios,
    delayed_commitment_scenario,
    paraphrase_query,
    quick_scenarios,
    scenario_with_paraphrase,
)
from packages.memory_core.services import MemoryService


def test_all_scenarios_are_registered() -> None:
    scenarios = all_scenarios()
    family_names = {scenario.family_name for scenario in scenarios}
    assert "delayed_commitment" in family_names
    assert "routine_interruption" in family_names
    assert "relationship_context" in family_names
    assert "commitment_revision" in family_names
    assert "identity_shift" in family_names
    assert len(scenarios) == len(SCENARIO_BUILDERS) * len(DEFAULT_SCENARIO_SEEDS)
    assert all("__seed_" in scenario.name for scenario in scenarios)


def test_eval_runner_reports_efficiency_metrics(memory_service: MemoryService) -> None:
    result = run_scenario(memory_service, "relationship_context")
    hierarchy_metrics = {metric.name: metric.value for metric in result.hierarchy_metrics}
    baseline_metrics = {metric.name: metric.value for metric in result.baseline_metrics}
    assert "token_efficiency_gain" in hierarchy_metrics
    assert "summary_node_count" in hierarchy_metrics
    assert "slot_recall" in hierarchy_metrics
    assert "slot_recall_per_token" in hierarchy_metrics
    assert "retrieved_token_count" in baseline_metrics
    assert "keyword_recall_per_token" in baseline_metrics
    assert "slot_recall" in baseline_metrics
    assert "recall_per_token_gain" in hierarchy_metrics
    assert "slot_recall_gain" in hierarchy_metrics
    assert hierarchy_metrics["retrieved_node_count"] >= 1


def test_delayed_commitment_setup_avoids_revision_like_routine_noise() -> None:
    scenario = delayed_commitment_scenario(11)
    routine_texts = [event.text.lower() for event in scenario.events if event.day_offset >= 2]
    assert not any("updated the roadmap board" in text for text in routine_texts)
    assert "action" in scenario.expected_slots
    assert "commitment" in scenario.expected_slots
    assert "commit to bringing" in scenario.query.lower()


def test_quick_subset_is_small_and_targeted() -> None:
    scenarios = quick_scenarios()
    assert len(scenarios) == len(QUICK_SCENARIO_FAMILIES)
    assert {scenario.family_name for scenario in scenarios} == set(QUICK_SCENARIO_FAMILIES)


def test_run_selected_quick_mode_executes(memory_service: MemoryService) -> None:
    results = run_selected(seeds=(11,), quick=True, service=memory_service)
    assert len(results) == len(QUICK_SCENARIO_FAMILIES)
    assert all(result.seed == 11 for result in results)


def test_query_paraphrase_changes_surface_form() -> None:
    query = "When is the prototype actually supposed to ship now?"
    paraphrased = paraphrase_query(query, "concise")
    assert paraphrased != query
    assert "ship" in paraphrased.lower()


def test_scenario_with_paraphrase_changes_name_agent_and_query() -> None:
    scenario = delayed_commitment_scenario(11)
    paraphrased = scenario_with_paraphrase(scenario, "indirect")
    assert paraphrased.name != scenario.name
    assert "__qp_indirect" in paraphrased.name
    assert paraphrased.agent_id != scenario.agent_id
    assert paraphrased.query != scenario.query
    assert paraphrased.expected_slots == scenario.expected_slots


def test_run_selected_with_paraphrases_expands_variants(memory_service: MemoryService) -> None:
    results = run_selected(
        seeds=(11,),
        families=("time_window_pressure",),
        paraphrase_styles=("concise", "colloquial"),
        service=memory_service,
    )
    assert len(results) == 2
    assert all("__qp_" in result.scenario_name for result in results)
    assert all(result.seed == 11 for result in results)


def test_paraphrase_styles_constant_has_expected_styles() -> None:
    assert set(QUERY_PARAPHRASE_STYLES) == {"concise", "indirect", "colloquial"}
