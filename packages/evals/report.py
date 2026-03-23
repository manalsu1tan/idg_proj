from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings
from packages.schemas.models import EvalRunResult, dump_model_json


REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def _metric_map(metrics: list[dict[str, Any]]) -> dict[str, float]:
    return {metric["name"]: float(metric["value"]) for metric in metrics}


def _latest_runs_by_scenario(raw_runs: list[dict[str, Any]]) -> list[EvalRunResult]:
    by_scenario: "OrderedDict[str, EvalRunResult]" = OrderedDict()
    for payload in sorted(raw_runs, key=lambda item: item.get("created_at") or ""):
        if hasattr(EvalRunResult, "model_validate"):
            run = EvalRunResult.model_validate(payload)
        else:
            run = EvalRunResult.parse_obj(payload)
        by_scenario[run.scenario_name] = run
    return list(by_scenario.values())


def build_report_payload(raw_runs: list[dict[str, Any]]) -> dict[str, Any]:
    runs = _latest_runs_by_scenario(raw_runs)
    exported_at = datetime.now(timezone.utc).isoformat()
    scenario_rows: list[dict[str, Any]] = []
    total_baseline_recall = 0.0
    total_hierarchy_recall = 0.0
    total_baseline_tokens = 0.0
    total_hierarchy_tokens = 0.0
    wins = 0
    ties = 0

    for run in runs:
        baseline = _metric_map([dump_model_json(metric) for metric in run.baseline_metrics])
        hierarchy = _metric_map([dump_model_json(metric) for metric in run.hierarchy_metrics])
        recall_gain = hierarchy.get("keyword_recall", 0.0) - baseline.get("keyword_recall", 0.0)
        token_delta = baseline.get("retrieved_token_count", 0.0) - hierarchy.get("retrieved_token_count", 0.0)
        if recall_gain > 0:
            wins += 1
        elif recall_gain == 0:
            ties += 1
        total_baseline_recall += baseline.get("keyword_recall", 0.0)
        total_hierarchy_recall += hierarchy.get("keyword_recall", 0.0)
        total_baseline_tokens += baseline.get("retrieved_token_count", 0.0)
        total_hierarchy_tokens += hierarchy.get("retrieved_token_count", 0.0)
        scenario_rows.append(
            {
                "scenario_name": run.scenario_name,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "notes": run.notes,
                "baseline": baseline,
                "hierarchy": hierarchy,
                "deltas": {
                    "keyword_recall_gain": recall_gain,
                    "retrieved_token_count_delta": token_delta,
                    "retrieval_depth_delta": hierarchy.get("retrieval_depth", 0.0) - baseline.get("retrieval_depth", 0.0),
                },
            }
        )

    count = max(len(scenario_rows), 1)
    summary = {
        "scenario_count": len(scenario_rows),
        "hierarchy_recall_win_count": wins,
        "recall_tie_count": ties,
        "baseline_avg_keyword_recall": total_baseline_recall / count,
        "hierarchy_avg_keyword_recall": total_hierarchy_recall / count,
        "avg_keyword_recall_gain": (total_hierarchy_recall - total_baseline_recall) / count,
        "baseline_avg_retrieved_tokens": total_baseline_tokens / count,
        "hierarchy_avg_retrieved_tokens": total_hierarchy_tokens / count,
        "avg_retrieved_token_delta": (total_baseline_tokens - total_hierarchy_tokens) / count,
    }
    return {
        "exported_at": exported_at,
        "report_type": "benchmark_eval_report",
        "source": "stored_eval_runs",
        "summary": summary,
        "scenarios": scenario_rows,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Benchmark Report",
        "",
        f"Generated: {report['exported_at']}",
        f"Source: {report['source']}",
        "",
        "## Summary",
        "",
        f"- Scenarios: {summary['scenario_count']}",
        f"- Hierarchy recall wins: {summary['hierarchy_recall_win_count']}",
        f"- Recall ties: {summary['recall_tie_count']}",
        f"- Average keyword recall: baseline {summary['baseline_avg_keyword_recall']:.3f}, hierarchy {summary['hierarchy_avg_keyword_recall']:.3f}",
        f"- Average recall gain: {summary['avg_keyword_recall_gain']:.3f}",
        f"- Average retrieved tokens: baseline {summary['baseline_avg_retrieved_tokens']:.1f}, hierarchy {summary['hierarchy_avg_retrieved_tokens']:.1f}",
        f"- Average retrieved token delta: {summary['avg_retrieved_token_delta']:.1f}",
        "",
        "## Scenario Results",
        "",
        "| Scenario | Baseline Recall | Hierarchy Recall | Recall Gain | Baseline Tokens | Hierarchy Tokens | Token Delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for scenario in report["scenarios"]:
        baseline = scenario["baseline"]
        hierarchy = scenario["hierarchy"]
        deltas = scenario["deltas"]
        lines.append(
            "| {scenario} | {b_recall:.3f} | {h_recall:.3f} | {gain:.3f} | {b_tokens:.1f} | {h_tokens:.1f} | {token_delta:.1f} |".format(
                scenario=scenario["scenario_name"],
                b_recall=baseline.get("keyword_recall", 0.0),
                h_recall=hierarchy.get("keyword_recall", 0.0),
                gain=deltas.get("keyword_recall_gain", 0.0),
                b_tokens=baseline.get("retrieved_token_count", 0.0),
                h_tokens=hierarchy.get("retrieved_token_count", 0.0),
                token_delta=deltas.get("retrieved_token_count_delta", 0.0),
            )
        )
    lines.extend(["", "## Notes", ""])
    for scenario in report["scenarios"]:
        notes = "; ".join(scenario["notes"]) if scenario.get("notes") else "No notes recorded."
        lines.append(f"- `{scenario['scenario_name']}`: {notes}")
    return "\n".join(lines) + "\n"


def export_report(service: MemoryService, output_dir: Path = REPORTS_DIR, stem: str | None = None) -> dict[str, Path]:
    report = build_report_payload(service.eval_runs())
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = stem or f"benchmark_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    json_path = output_dir / f"{safe_stem}.json"
    md_path = output_dir / f"{safe_stem}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a benchmark report from stored eval runs.")
    parser.add_argument("--output-dir", default=str(REPORTS_DIR), help="Directory to write report artifacts into.")
    parser.add_argument("--stem", default=None, help="Optional file stem for the generated report files.")
    args = parser.parse_args()
    service = MemoryService(load_settings())
    paths = export_report(service, output_dir=Path(args.output_dir), stem=args.stem)
    print(
        json.dumps(
            {key: str(value) for key, value in paths.items()},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
