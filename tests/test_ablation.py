from __future__ import annotations

from packages.evals.ablation import build_ablation_report, run_ablation_scenario
from packages.memory_core.services import MemoryService


def test_ablation_runner_reports_winning_mode(memory_service: MemoryService) -> None:
    result = run_ablation_scenario(memory_service, 'delayed_commitment')
    assert result.mode_results
    modes = {mode_result.mode.value for mode_result in result.mode_results}
    assert 'flat_baseline' in modes
    assert 'hierarchy_summary_only' in modes
    assert 'hierarchy_balanced' in modes
    assert 'hierarchy_drill_down' in modes
    assert 'hierarchy_top_leaf_only' in modes

    report = build_ablation_report([result])
    assert report['report_type'] == 'benchmark_ablation_report'
    assert report['summary']['scenario_count'] == 1
    assert report['scenarios'][0]['best_mode'] in modes
    metric_names = {metric.name for metric in result.mode_results[0].metrics}
    assert 'slot_recall' in metric_names
    assert 'slot_recall_per_token' in metric_names
