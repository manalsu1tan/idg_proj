from __future__ import annotations

"""Scenario runner entrypoints
Executes eval scenarios and computes metrics"""

import argparse
import json
import statistics
from datetime import datetime

from packages.evals.scenarios import (
    DEFAULT_SCENARIO_SEEDS,
    QUERY_PARAPHRASE_STYLES,
    Scenario,
    all_scenarios,
    get_scenario,
    quick_scenarios,
    scenario_timestamp,
    scenario_with_paraphrase,
)
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings
from packages.schemas.models import BuildSummariesRequest, EvalMetric, EvalRunResult, QueryMode, RefreshRequest, dump_model


def keyword_recall(text: str, expected_keywords: list[str]) -> float:
    """Compute keyword recall score"""
    lowered = text.lower()
    matches = sum(1 for keyword in expected_keywords if keyword.lower() in lowered)
    return matches / max(len(expected_keywords), 1)


def metric(name: str, value: float, **details) -> EvalMetric:
    """Small helper to build EvalMetric"""
    return EvalMetric(name=name, value=value, details=details)


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def slot_recall(text: str, expected_slots: dict[str, list[str]]) -> tuple[float, dict[str, float]]:
    """Compute slot level recall map and mean score"""
    lowered = _normalized_text(text)
    per_slot: dict[str, float] = {}
    for slot_name, expected_values in expected_slots.items():
        normalized_values = [_normalized_text(value) for value in expected_values]
        per_slot[slot_name] = 1.0 if all(value in lowered for value in normalized_values) else 0.0
    average = statistics.fmean(per_slot.values()) if per_slot else 0.0
    return average, per_slot


def _recall_text(response) -> str:
    # measure recall from retrieved evidence only
    snippets: list[str] = []
    seen_ids: set[str] = set()
    for item in response.retrieved_nodes:
        node_id = item.node.node_id
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        snippets.append(item.node.text)
    return "\n".join(snippets)


def run_scenario_instance(service: MemoryService, scenario: Scenario) -> EvalRunResult:
    """Run one scenario end to end
    Ingests events builds summaries runs flat and hierarchy retrieval then records eval"""
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
    baseline = service.retrieve_flat(
        agent_id=scenario.agent_id,
        query=scenario.query,
        query_time=scenario_timestamp(scenario.query_day_offset),
        token_budget=120,
        branch_limit=1,
    )
    hierarchy = service.retrieve(
        agent_id=scenario.agent_id,
        query=scenario.query,
        query_time=scenario_timestamp(scenario.query_day_offset),
        mode=QueryMode.BALANCED,
        token_budget=120,
        branch_limit=3,
    )
    if built:
        service.refresh(
            RefreshRequest(
                agent_id=scenario.agent_id,
                changed_node_ids=[built[0].child_ids[0]],
            )
        )
    baseline_recall_text = _recall_text(baseline)
    hierarchy_recall_text = _recall_text(hierarchy)
    baseline_recall = keyword_recall(baseline_recall_text, scenario.expected_keywords)
    hierarchy_recall = keyword_recall(hierarchy_recall_text, scenario.expected_keywords)
    baseline_slot_recall, baseline_slot_map = slot_recall(baseline_recall_text, scenario.expected_slots)
    hierarchy_slot_recall, hierarchy_slot_map = slot_recall(hierarchy_recall_text, scenario.expected_slots)
    baseline_recall_per_token = baseline_recall / max(float(baseline.diagnostics.retrieved_token_count), 1.0)
    hierarchy_recall_per_token = hierarchy_recall / max(float(hierarchy.diagnostics.retrieved_token_count), 1.0)
    baseline_slot_recall_per_token = baseline_slot_recall / max(float(baseline.diagnostics.retrieved_token_count), 1.0)
    hierarchy_slot_recall_per_token = hierarchy_slot_recall / max(float(hierarchy.diagnostics.retrieved_token_count), 1.0)
    baseline_metrics = [
        metric("keyword_recall", baseline_recall),
        metric("slot_recall", baseline_slot_recall, slot_count=len(scenario.expected_slots), **baseline_slot_map),
        metric("retrieval_depth", float(baseline.retrieval_depth)),
        metric("token_budget", float(baseline.token_budget)),
        metric("retrieved_token_count", float(baseline.diagnostics.retrieved_token_count)),
        metric("retrieved_node_count", float(baseline.diagnostics.retrieved_node_count)),
        metric("keyword_recall_per_token", baseline_recall_per_token),
        metric("keyword_recall_per_100_tokens", baseline_recall_per_token * 100.0),
        metric("slot_recall_per_token", baseline_slot_recall_per_token),
        metric("slot_recall_per_100_tokens", baseline_slot_recall_per_token * 100.0),
        metric("fallback_used", 1.0 if baseline.diagnostics.fallback_used else 0.0),
    ]
    hierarchy_metrics = [
        metric("keyword_recall", hierarchy_recall),
        metric("slot_recall", hierarchy_slot_recall, slot_count=len(scenario.expected_slots), **hierarchy_slot_map),
        metric("retrieval_depth", float(hierarchy.retrieval_depth)),
        metric("token_budget", float(hierarchy.token_budget)),
        metric("summary_count", float(len(built))),
        metric("retrieved_token_count", float(hierarchy.diagnostics.retrieved_token_count)),
        metric("retrieved_node_count", float(hierarchy.diagnostics.retrieved_node_count)),
        metric("summary_node_count", float(hierarchy.diagnostics.summary_node_count)),
        metric("supporting_leaf_count", float(hierarchy.diagnostics.supporting_leaf_count)),
        metric("branch_count", float(hierarchy.diagnostics.branch_count)),
        metric("keyword_recall_per_token", hierarchy_recall_per_token),
        metric("keyword_recall_per_100_tokens", hierarchy_recall_per_token * 100.0),
        metric("slot_recall_per_token", hierarchy_slot_recall_per_token),
        metric("slot_recall_per_100_tokens", hierarchy_slot_recall_per_token * 100.0),
        metric("fallback_used", 1.0 if hierarchy.diagnostics.fallback_used else 0.0),
        metric(
            "routing_attribution",
            1.0 if hierarchy.diagnostics.routing_strategy else 0.0,
            routing_strategy=hierarchy.diagnostics.routing_strategy,
            fired_rules=hierarchy.diagnostics.fired_rules,
            query_feature_scores=hierarchy.diagnostics.query_feature_scores,
        ),
        metric(
            "token_efficiency_gain",
            float(baseline.diagnostics.retrieved_token_count - hierarchy.diagnostics.retrieved_token_count),
            baseline_tokens=baseline.diagnostics.retrieved_token_count,
            hierarchy_tokens=hierarchy.diagnostics.retrieved_token_count,
        ),
        metric(
            "recall_per_token_gain",
            hierarchy_recall_per_token - baseline_recall_per_token,
            baseline_recall_per_token=baseline_recall_per_token,
            hierarchy_recall_per_token=hierarchy_recall_per_token,
        ),
        metric(
            "slot_recall_gain",
            hierarchy_slot_recall - baseline_slot_recall,
            baseline_slot_recall=baseline_slot_recall,
            hierarchy_slot_recall=hierarchy_slot_recall,
        ),
        metric(
            "slot_recall_per_token_gain",
            hierarchy_slot_recall_per_token - baseline_slot_recall_per_token,
            baseline_slot_recall_per_token=baseline_slot_recall_per_token,
            hierarchy_slot_recall_per_token=hierarchy_slot_recall_per_token,
        ),
    ]
    result = EvalRunResult(
        scenario_name=scenario.name,
        family_name=scenario.family_name,
        instance_id=scenario.name,
        seed=scenario.seed,
        baseline_metrics=baseline_metrics,
        hierarchy_metrics=hierarchy_metrics,
        notes=scenario.notes,
        created_at=datetime.utcnow(),
    )
    service.record_eval(result)
    return result


def run_scenario(service: MemoryService, scenario_name: str) -> EvalRunResult:
    scenario = get_scenario(scenario_name)
    return run_scenario_instance(service, scenario)


def run_all() -> list[EvalRunResult]:
    """Run complete scenario catalog with default config
    Creates fresh service instances per scenario for isolation"""
    results = []
    for scenario in all_scenarios():
        results.append(run_scenario_instance(MemoryService(load_settings()), scenario))
    return results


def run_selected(
    *,
    seeds: tuple[int, ...] = DEFAULT_SCENARIO_SEEDS,
    families: tuple[str, ...] | None = None,
    scenario_names: tuple[str, ...] | None = None,
    quick: bool = False,
    paraphrase_styles: tuple[str, ...] | None = None,
    service: MemoryService | None = None,
) -> list[EvalRunResult]:
    """Run filtered scenario subset
    Supports seed family scenario name quick mode and paraphrase variants"""
    service = service or MemoryService(load_settings())
    if scenario_names:
        selected = [get_scenario(name, seeds=seeds) for name in scenario_names]
    elif quick:
        selected = quick_scenarios(seeds=seeds[:1] if seeds else (DEFAULT_SCENARIO_SEEDS[0],))
    else:
        selected = all_scenarios(seeds=seeds)
        if families:
            family_filter = set(families)
            selected = [scenario for scenario in selected if scenario.family_name in family_filter]
    if paraphrase_styles:
        selected = [scenario_with_paraphrase(scenario, style) for scenario in selected for style in paraphrase_styles]
    return [run_scenario_instance(service, scenario) for scenario in selected]


def main() -> None:
    """CLI entrypoint for eval runner"""
    parser = argparse.ArgumentParser(description="Run benchmark eval scenarios.")
    parser.add_argument(
        "--seed",
        dest="seeds",
        action="append",
        type=int,
        help="Optional seed override. Repeat for multiple seeds.",
    )
    parser.add_argument(
        "--family",
        dest="families",
        action="append",
        help="Optional scenario family filter. Repeat for multiple families.",
    )
    parser.add_argument(
        "--scenario",
        dest="scenarios",
        action="append",
        help="Optional explicit scenario name or family alias. Repeat for multiple values.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a small focused subset (4 families x first seed) for fast iteration.",
    )
    parser.add_argument(
        "--paraphrase-style",
        dest="paraphrase_styles",
        action="append",
        choices=list(QUERY_PARAPHRASE_STYLES),
        help="Run paraphrased query variants only. Repeat for multiple styles.",
    )
    parser.add_argument(
        "--all-paraphrases",
        action="store_true",
        help="Shortcut for running all supported query paraphrase styles.",
    )
    args = parser.parse_args()

    seeds = tuple(args.seeds) if args.seeds else DEFAULT_SCENARIO_SEEDS
    families = tuple(args.families) if args.families else None
    scenarios = tuple(args.scenarios) if args.scenarios else None
    paraphrase_styles: tuple[str, ...] | None = None
    if args.all_paraphrases:
        paraphrase_styles = QUERY_PARAPHRASE_STYLES
    elif args.paraphrase_styles:
        paraphrase_styles = tuple(args.paraphrase_styles)
    payload = [
        dump_model(result)
        for result in run_selected(
            seeds=seeds,
            families=families,
            scenario_names=scenarios,
            quick=args.quick,
            paraphrase_styles=paraphrase_styles,
        )
    ]
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
