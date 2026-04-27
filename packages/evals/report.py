from __future__ import annotations

"""Eval report helpers
Builds aggregate payloads and markdown output"""

import argparse
import json
import statistics
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings
from packages.schemas.models import EvalRunResult, dump_model_json


REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def _metric_map(metrics: list[dict[str, Any]]) -> dict[str, float]:
    """Map metric rows to numeric value dict"""
    return {metric["name"]: float(metric["value"]) for metric in metrics}


def _latest_runs_by_scenario(raw_runs: list[dict[str, Any]]) -> list[EvalRunResult]:
    """Keep latest run per scenario name"""
    by_scenario: "OrderedDict[str, EvalRunResult]" = OrderedDict()
    for payload in sorted(raw_runs, key=lambda item: item.get("created_at") or ""):
        if hasattr(EvalRunResult, "model_validate"):
            run = EvalRunResult.model_validate(payload)
        else:
            run = EvalRunResult.parse_obj(payload)
        by_scenario[run.scenario_name] = run
    return list(by_scenario.values())


def _mean(values: list[float]) -> float:
    """Return a safe mean"""
    return statistics.fmean(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    """Return a safe population stddev"""
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _winner(baseline: dict[str, float], hierarchy: dict[str, float]) -> str:
    """Pick the winning retriever for one scenario"""
    baseline_slot = baseline.get("slot_recall", 0.0)
    hierarchy_slot = hierarchy.get("slot_recall", 0.0)
    if hierarchy_slot > baseline_slot:
        return "hierarchy"
    if hierarchy_slot < baseline_slot:
        return "flat"
    baseline_keyword = baseline.get("keyword_recall", 0.0)
    hierarchy_keyword = hierarchy.get("keyword_recall", 0.0)
    if hierarchy_keyword > baseline_keyword:
        return "hierarchy"
    if hierarchy_keyword < baseline_keyword:
        return "flat"
    baseline_tokens = baseline.get("retrieved_token_count", 0.0)
    hierarchy_tokens = hierarchy.get("retrieved_token_count", 0.0)
    if hierarchy_tokens < baseline_tokens:
        return "hierarchy"
    if hierarchy_tokens > baseline_tokens:
        return "flat"
    return "tie"


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate baseline hierarchy and delta stats"""
    baseline_keyword = [row["baseline"].get("keyword_recall", 0.0) for row in rows]
    hierarchy_keyword = [row["hierarchy"].get("keyword_recall", 0.0) for row in rows]
    baseline_slot = [row["baseline"].get("slot_recall", 0.0) for row in rows]
    hierarchy_slot = [row["hierarchy"].get("slot_recall", 0.0) for row in rows]
    baseline_tokens = [row["baseline"].get("retrieved_token_count", 0.0) for row in rows]
    hierarchy_tokens = [row["hierarchy"].get("retrieved_token_count", 0.0) for row in rows]
    baseline_slot_per_token = [row["baseline"].get("slot_recall_per_token", 0.0) for row in rows]
    hierarchy_slot_per_token = [row["hierarchy"].get("slot_recall_per_token", 0.0) for row in rows]

    wins = sum(1 for row in rows if row["winner"] == "hierarchy")
    flat_wins = sum(1 for row in rows if row["winner"] == "flat")
    ties = sum(1 for row in rows if row["winner"] == "tie")
    count = max(len(rows), 1)
    return {
        "instance_count": len(rows),
        "hierarchy_win_count": wins,
        "flat_win_count": flat_wins,
        "tie_count": ties,
        "hierarchy_win_rate": wins / count,
        "flat_win_rate": flat_wins / count,
        "tie_rate": ties / count,
        "baseline_keyword_recall_mean": _mean(baseline_keyword),
        "baseline_keyword_recall_stddev": _stddev(baseline_keyword),
        "hierarchy_keyword_recall_mean": _mean(hierarchy_keyword),
        "hierarchy_keyword_recall_stddev": _stddev(hierarchy_keyword),
        "baseline_slot_recall_mean": _mean(baseline_slot),
        "baseline_slot_recall_stddev": _stddev(baseline_slot),
        "hierarchy_slot_recall_mean": _mean(hierarchy_slot),
        "hierarchy_slot_recall_stddev": _stddev(hierarchy_slot),
        "baseline_retrieved_tokens_mean": _mean(baseline_tokens),
        "baseline_retrieved_tokens_stddev": _stddev(baseline_tokens),
        "hierarchy_retrieved_tokens_mean": _mean(hierarchy_tokens),
        "hierarchy_retrieved_tokens_stddev": _stddev(hierarchy_tokens),
        "baseline_slot_recall_per_token_mean": _mean(baseline_slot_per_token),
        "hierarchy_slot_recall_per_token_mean": _mean(hierarchy_slot_per_token),
        "avg_keyword_recall_gain": _mean([h - b for b, h in zip(baseline_keyword, hierarchy_keyword)]),
        "avg_slot_recall_gain": _mean([h - b for b, h in zip(baseline_slot, hierarchy_slot)]),
        "avg_retrieved_token_delta": _mean([b - h for b, h in zip(baseline_tokens, hierarchy_tokens)]),
        "avg_slot_recall_per_token_gain": _mean([h - b for b, h in zip(baseline_slot_per_token, hierarchy_slot_per_token)]),
    }


def build_report_payload(raw_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build benchmark report payload from stored eval runs
    Aggregates scenario and family metrics plus wins deltas and variance stats"""
    runs = _latest_runs_by_scenario(raw_runs)
    exported_at = datetime.now(timezone.utc).isoformat()
    scenario_rows: list[dict[str, Any]] = []

    for run in runs:
        # Normalize both metric sets before computing deltas
        baseline = _metric_map([dump_model_json(metric) for metric in run.baseline_metrics])
        hierarchy = _metric_map([dump_model_json(metric) for metric in run.hierarchy_metrics])
        winner = _winner(baseline, hierarchy)
        scenario_rows.append(
            {
                "scenario_name": run.scenario_name,
                "family_name": run.family_name or run.scenario_name,
                "instance_id": run.instance_id or run.scenario_name,
                "seed": run.seed,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "notes": run.notes,
                "winner": winner,
                "baseline": baseline,
                "hierarchy": hierarchy,
                "deltas": {
                    "keyword_recall_gain": hierarchy.get("keyword_recall", 0.0) - baseline.get("keyword_recall", 0.0),
                    "slot_recall_gain": hierarchy.get("slot_recall", 0.0) - baseline.get("slot_recall", 0.0),
                    "retrieved_token_count_delta": baseline.get("retrieved_token_count", 0.0)
                    - hierarchy.get("retrieved_token_count", 0.0),
                    "retrieval_depth_delta": hierarchy.get("retrieval_depth", 0.0) - baseline.get("retrieval_depth", 0.0),
                },
            }
        )

    family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scenario_rows:
        family_groups[row["family_name"]].append(row)

    family_rows = []
    for family_name in sorted(family_groups):
        # Reuse the same aggregation path for families and globals
        family_rows.append(
            {
                "family_name": family_name,
                **_aggregate_rows(family_groups[family_name]),
            }
        )

    summary = {
        "scenario_count": len(scenario_rows),
        "family_count": len(family_rows),
        **_aggregate_rows(scenario_rows),
    }
    return {
        "exported_at": exported_at,
        "report_type": "benchmark_eval_report",
        "source": "stored_eval_runs",
        "summary": summary,
        "families": family_rows,
        "scenarios": scenario_rows,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render benchmark report payload as markdown
    Emits summary family tables scenario rows and notes section"""
    summary = report["summary"]
    lines = [
        "# Benchmark Report",
        "",
        f"Generated: {report['exported_at']}",
        f"Source: {report['source']}",
        "",
        "## Summary",
        "",
        f"- Scenario instances: {summary['scenario_count']}",
        f"- Scenario families: {summary['family_count']}",
        f"- Hierarchy win rate: {summary['hierarchy_win_rate']:.3f}",
        f"- Flat win rate: {summary['flat_win_rate']:.3f}",
        f"- Tie rate: {summary['tie_rate']:.3f}",
        f"- Slot recall mean +/- stddev: baseline {summary['baseline_slot_recall_mean']:.3f} +/- {summary['baseline_slot_recall_stddev']:.3f}, hierarchy {summary['hierarchy_slot_recall_mean']:.3f} +/- {summary['hierarchy_slot_recall_stddev']:.3f}",
        f"- Keyword recall mean +/- stddev: baseline {summary['baseline_keyword_recall_mean']:.3f} +/- {summary['baseline_keyword_recall_stddev']:.3f}, hierarchy {summary['hierarchy_keyword_recall_mean']:.3f} +/- {summary['hierarchy_keyword_recall_stddev']:.3f}",
        f"- Retrieved tokens mean +/- stddev: baseline {summary['baseline_retrieved_tokens_mean']:.1f} +/- {summary['baseline_retrieved_tokens_stddev']:.1f}, hierarchy {summary['hierarchy_retrieved_tokens_mean']:.1f} +/- {summary['hierarchy_retrieved_tokens_stddev']:.1f}",
        f"- Average slot recall gain: {summary['avg_slot_recall_gain']:.3f}",
        f"- Average keyword recall gain: {summary['avg_keyword_recall_gain']:.3f}",
        f"- Average retrieved token delta: {summary['avg_retrieved_token_delta']:.1f}",
        "",
        "## Family Aggregates",
        "",
        "| Family | Instances | Hierarchy Win Rate | Flat Win Rate | Slot Recall Gain | Token Delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family in report["families"]:
        lines.append(
            "| {family_name} | {instance_count} | {hierarchy_win_rate:.3f} | {flat_win_rate:.3f} | {avg_slot_recall_gain:.3f} | {avg_retrieved_token_delta:.1f} |".format(
                **family
            )
        )
    lines.extend(
        [
            "",
            "## Scenario Instances",
            "",
            "| Scenario | Seed | Winner | Baseline Slot Recall | Hierarchy Slot Recall | Baseline Tokens | Hierarchy Tokens |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for scenario in report["scenarios"]:
        baseline = scenario["baseline"]
        hierarchy = scenario["hierarchy"]
        lines.append(
            "| {scenario} | {seed} | {winner} | {b_slot:.3f} | {h_slot:.3f} | {b_tokens:.1f} | {h_tokens:.1f} |".format(
                scenario=scenario["scenario_name"],
                seed=scenario.get("seed", 0),
                winner=scenario["winner"],
                b_slot=baseline.get("slot_recall", 0.0),
                h_slot=hierarchy.get("slot_recall", 0.0),
                b_tokens=baseline.get("retrieved_token_count", 0.0),
                h_tokens=hierarchy.get("retrieved_token_count", 0.0),
            )
        )
    lines.extend(["", "## Notes", ""])
    for scenario in report["scenarios"]:
        notes = "; ".join(scenario["notes"]) if scenario.get("notes") else "No notes recorded."
        lines.append(f"- `{scenario['scenario_name']}`: {notes}")
    return "\n".join(lines) + "\n"


def export_report(service: MemoryService, output_dir: Path = REPORTS_DIR, stem: str | None = None) -> dict[str, Path]:
    """Export report payload and markdown files
    Returns output paths for downstream cli and api use"""
    report = build_report_payload(service.eval_runs())
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = stem or f"benchmark_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    json_path = output_dir / f"{safe_stem}.json"
    md_path = output_dir / f"{safe_stem}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def main() -> None:
    """Run the report export cli"""
    parser = argparse.ArgumentParser(description="Export a benchmark report from stored eval runs.")
    parser.add_argument("--output-dir", default=str(REPORTS_DIR), help="Directory to write report artifacts into.")
    parser.add_argument("--stem", default=None, help="Optional file stem for the generated report files.")
    args = parser.parse_args()
    service = MemoryService(load_settings())
    paths = export_report(service, output_dir=Path(args.output_dir), stem=args.stem)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
