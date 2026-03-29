from __future__ import annotations

from packages.evals.runner import run_scenario
from packages.evals.scenarios import DEFAULT_SCENARIO_SEEDS, all_scenarios
from packages.memory_core.services import MemoryService


def test_all_scenarios_are_registered() -> None:
    scenarios = all_scenarios()
    family_names = {scenario.family_name for scenario in scenarios}
    assert "delayed_commitment" in family_names
    assert "routine_interruption" in family_names
    assert "relationship_context" in family_names
    assert "commitment_revision" in family_names
    assert "identity_shift" in family_names
    assert len(scenarios) == 5 * len(DEFAULT_SCENARIO_SEEDS)
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
