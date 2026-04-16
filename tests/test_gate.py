from __future__ import annotations

"""Test module overview for test gate
Covers behavior and regression checks"""

from packages.evals.gate import run_generalization_gate
from packages.memory_core.services import MemoryService


def test_generalization_gate_runs_with_small_slice(memory_service: MemoryService) -> None:
    report = run_generalization_gate(
        seeds=(11,),
        families=("time_window_pressure",),
        paraphrase_styles=("concise",),
        service=memory_service,
    )
    assert report["report_type"] == "generalization_gate_report"
    assert report["summary"]["scenario_count"] == 2
    assert report["family_variant_metrics"]
