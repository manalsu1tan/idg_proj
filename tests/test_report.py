from __future__ import annotations

"""Test module overview for test report
Covers behavior and regression checks"""

import json

from packages.evals.report import build_report_payload, export_report
from packages.evals.runner import run_scenario
from packages.memory_core.services import MemoryService


def test_benchmark_report_export_writes_json_and_markdown(memory_service: MemoryService, tmp_path) -> None:
    run_scenario(memory_service, 'relationship_context')
    run_scenario(memory_service, 'identity_shift')

    report = build_report_payload(memory_service.eval_runs())
    assert report['summary']['scenario_count'] == 2
    assert report['summary']['family_count'] >= 2
    assert 'baseline_slot_recall_mean' in report['summary']
    assert 'hierarchy_win_rate' in report['summary']
    assert report['families']

    paths = export_report(memory_service, output_dir=tmp_path, stem='benchmark_test')
    assert paths['json'].exists()
    assert paths['markdown'].exists()

    payload = json.loads(paths['json'].read_text(encoding='utf-8'))
    assert payload['report_type'] == 'benchmark_eval_report'
    markdown = paths['markdown'].read_text(encoding='utf-8')
    assert '# Benchmark Report' in markdown
    assert 'Family Aggregates' in markdown
    assert 'relationship_context' in markdown
