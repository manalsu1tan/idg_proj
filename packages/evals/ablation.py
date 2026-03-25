from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from packages.evals.scenarios import all_scenarios, scenario_timestamp
from packages.evals.runner import keyword_recall, metric
from packages.memory_core.services import CandidateScore, MemoryService, build_retrieval_diagnostics
from packages.memory_core.settings import load_settings
from packages.schemas.models import (
    AblationMode,
    AblationModeResult,
    AblationRunResult,
    BuildSummariesRequest,
    EvalMetric,
    QueryMode,
    RefreshRequest,
    RetrieveResponse,
    RetrievedNode,
    RetrievalTrace,
    RetrievalTraceEntry,
    dump_model,
    dump_model_json,
)


REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def _metrics_from_response(mode: AblationMode, response: RetrieveResponse, summary_count: int) -> AblationModeResult:
    metrics = [
        metric("retrieval_depth", float(response.retrieval_depth)),
        metric("token_budget", float(response.token_budget)),
        metric("retrieved_token_count", float(response.diagnostics.retrieved_token_count)),
        metric("retrieved_node_count", float(response.diagnostics.retrieved_node_count)),
        metric("summary_node_count", float(response.diagnostics.summary_node_count)),
        metric("supporting_leaf_count", float(response.diagnostics.supporting_leaf_count)),
        metric("branch_count", float(response.diagnostics.branch_count)),
        metric("fallback_used", 1.0 if response.diagnostics.fallback_used else 0.0),
        metric("summary_count", float(summary_count)),
    ]
    return AblationModeResult(mode=mode, metrics=metrics)


def _append_recall_metrics(result: AblationModeResult, response: RetrieveResponse, expected_keywords: list[str]) -> AblationModeResult:
    recall = keyword_recall(response.packed_context, expected_keywords)
    recall_per_token = recall / max(float(response.diagnostics.retrieved_token_count), 1.0)
    result.metrics = [
        metric("keyword_recall", recall),
        *result.metrics,
        metric("keyword_recall_per_token", recall_per_token),
        metric("keyword_recall_per_100_tokens", recall_per_token * 100.0),
    ]
    return result


def _top_leaf_only_response(service: MemoryService, *, agent_id: str, query: str, query_time: datetime, token_budget: int) -> RetrieveResponse:
    retrieved, depth, trace_entries = service.hierarchical_retriever.retrieve(
        agent_id=agent_id,
        query=query,
        query_time=query_time,
        mode=QueryMode.DRILL_DOWN,
        token_budget=token_budget,
        branch_limit=1,
    )
    leaf_candidates = [candidate for candidate in retrieved if candidate.node.level.value == "L0"]
    selected = leaf_candidates[:1] if leaf_candidates else retrieved[:1]
    selected_ids = {candidate.node.node_id for candidate in selected}
    selected_entries = [entry for entry in trace_entries if entry.node_id in selected_ids]
    packed = service.context_packer.pack(query, selected, token_budget)
    diagnostics = build_retrieval_diagnostics(selected, selected_entries, packed)
    trace = RetrievalTrace(
        trace_id=str(uuid.uuid4()),
        agent_id=agent_id,
        query=query,
        mode=QueryMode.DRILL_DOWN,
        token_budget=token_budget,
        retrieval_depth=depth if selected else 0,
        created_at=datetime.utcnow(),
        entries=selected_entries,
        diagnostics=diagnostics,
    )
    service.store.write_retrieval_trace(trace)
    return RetrieveResponse(
        query=query,
        mode=QueryMode.DRILL_DOWN,
        token_budget=token_budget,
        retrieved_nodes=[
            RetrievedNode(
                node=item.node,
                score=item.score,
                branch_root_id=item.node.parent_ids[0] if item.node.parent_ids else None,
                relevance_score=item.relevance,
                recency_score=item.recency,
                importance_score=item.node.importance_score,
                selected_as=next((entry.selected_as for entry in selected_entries if entry.node_id == item.node.node_id), None),
                selection_reason=next((entry.selection_reason for entry in selected_entries if entry.node_id == item.node.node_id), None),
            )
            for item in selected
        ],
        packed_context=packed,
        retrieval_depth=depth if selected else 0,
        trace_id=trace.trace_id,
        trace_entries=selected_entries,
        diagnostics=diagnostics,
    )


def _best_mode(mode_results: list[AblationModeResult]) -> AblationMode:
    def score_tuple(result: AblationModeResult) -> tuple[float, float, float]:
        metric_map = {item.name: item.value for item in result.metrics}
        return (
            metric_map.get("keyword_recall", 0.0),
            metric_map.get("keyword_recall_per_token", 0.0),
            -metric_map.get("retrieved_token_count", 0.0),
        )

    return max(mode_results, key=score_tuple).mode


def run_ablation_scenario(service: MemoryService, scenario_name: str) -> AblationRunResult:
    scenario = next(item for item in all_scenarios() if item.name == scenario_name)
    for event in scenario.events:
        service.agent_loop.observe(
            agent_id=scenario.agent_id,
            text=event.text,
            timestamp=scenario_timestamp(event.day_offset),
            importance_score=event.importance,
        )
    built = service.build_summaries(
        BuildSummariesRequest(agent_id=scenario.agent_id, query_time=scenario_timestamp(scenario.query_day_offset))
    )
    if built:
        service.refresh(
            RefreshRequest(
                agent_id=scenario.agent_id,
                changed_node_ids=[built[0].child_ids[0]],
            )
        )

    query_kwargs = {
        "agent_id": scenario.agent_id,
        "query": scenario.query,
        "query_time": scenario_timestamp(scenario.query_day_offset),
        "token_budget": 120,
    }

    runners: dict[AblationMode, Callable[[], RetrieveResponse]] = {
        AblationMode.FLAT_BASELINE: lambda: service.retrieve_flat(branch_limit=1, **query_kwargs),
        AblationMode.HIERARCHY_SUMMARY_ONLY: lambda: service.retrieve(mode=QueryMode.SUMMARY_ONLY, branch_limit=3, **query_kwargs),
        AblationMode.HIERARCHY_BALANCED: lambda: service.retrieve(mode=QueryMode.BALANCED, branch_limit=3, **query_kwargs),
        AblationMode.HIERARCHY_DRILL_DOWN: lambda: service.retrieve(mode=QueryMode.DRILL_DOWN, branch_limit=1, **query_kwargs),
        AblationMode.HIERARCHY_TOP_LEAF_ONLY: lambda: _top_leaf_only_response(service, **query_kwargs),
    }

    mode_results: list[AblationModeResult] = []
    for mode, runner in runners.items():
        response = runner()
        result = _metrics_from_response(mode, response, summary_count=len(built))
        result = _append_recall_metrics(result, response, scenario.expected_keywords)
        mode_results.append(result)

    return AblationRunResult(
        scenario_name=scenario.name,
        mode_results=mode_results,
        best_mode=_best_mode(mode_results),
        notes=scenario.notes,
        created_at=datetime.utcnow(),
    )


def run_all_ablations() -> list[AblationRunResult]:
    results = []
    for scenario in all_scenarios():
        results.append(run_ablation_scenario(MemoryService(load_settings()), scenario.name))
    return results


def build_ablation_report(results: list[AblationRunResult]) -> dict:
    exported_at = datetime.now(timezone.utc).isoformat()
    rows = []
    winners: dict[str, int] = {mode.value: 0 for mode in AblationMode}
    for result in results:
        winners[result.best_mode.value] += 1
        rows.append(
            {
                "scenario_name": result.scenario_name,
                "best_mode": result.best_mode.value,
                "notes": result.notes,
                "mode_results": [dump_model_json(mode_result) for mode_result in result.mode_results],
                "created_at": result.created_at.isoformat() if result.created_at else None,
            }
        )
    return {
        "exported_at": exported_at,
        "report_type": "benchmark_ablation_report",
        "source": "on_demand_ablation_run",
        "summary": {
            "scenario_count": len(results),
            "winner_counts": winners,
        },
        "scenarios": rows,
    }


def render_ablation_markdown(report: dict) -> str:
    lines = [
        "# Benchmark Ablation Report",
        "",
        f"Generated: {report['exported_at']}",
        "",
        "## Winner Counts",
        "",
    ]
    for mode, count in report["summary"]["winner_counts"].items():
        lines.append(f"- `{mode}`: {count}")
    lines.extend(["", "## Scenario Winners", "", "| Scenario | Best Mode | |", "| --- | --- | --- |"])
    for scenario in report["scenarios"]:
        lines.append(f"| {scenario['scenario_name']} | {scenario['best_mode']} | |")
    lines.extend(["", "## Per-Scenario Details", ""])
    for scenario in report["scenarios"]:
        lines.append(f"### {scenario['scenario_name']}")
        lines.append("")
        lines.append(f"- Best mode: `{scenario['best_mode']}`")
        notes = "; ".join(scenario["notes"]) if scenario.get("notes") else "No notes recorded."
        lines.append(f"- Notes: {notes}")
        lines.append("")
        lines.append("| Mode | Recall | Recall/Token | Tokens | Depth | Nodes |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for mode_result in scenario["mode_results"]:
            metric_map = {metric["name"]: metric["value"] for metric in mode_result["metrics"]}
            lines.append(
                "| {mode} | {recall:.3f} | {rpt:.3f} | {tokens:.1f} | {depth:.1f} | {nodes:.1f} |".format(
                    mode=mode_result["mode"],
                    recall=metric_map.get("keyword_recall", 0.0),
                    rpt=metric_map.get("keyword_recall_per_token", 0.0),
                    tokens=metric_map.get("retrieved_token_count", 0.0),
                    depth=metric_map.get("retrieval_depth", 0.0),
                    nodes=metric_map.get("retrieved_node_count", 0.0),
                )
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def export_ablation_report(results: list[AblationRunResult], output_dir: Path = REPORTS_DIR, stem: str | None = None) -> dict[str, Path]:
    report = build_ablation_report(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = stem or f"benchmark_ablation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    json_path = output_dir / f"{safe_stem}.json"
    md_path = output_dir / f"{safe_stem}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_ablation_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark retrieval ablations.")
    parser.add_argument("--output-dir", default=str(REPORTS_DIR), help="Directory to write ablation report artifacts into.")
    parser.add_argument("--stem", default=None, help="Optional file stem for generated ablation report files.")
    args = parser.parse_args()
    results = run_all_ablations()
    paths = export_ablation_report(results, output_dir=Path(args.output_dir), stem=args.stem)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
