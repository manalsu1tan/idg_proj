from __future__ import annotations

import json
import statistics
from datetime import datetime

from packages.evals.scenarios import all_scenarios, get_scenario, scenario_timestamp
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings
from packages.schemas.models import BuildSummariesRequest, EvalMetric, EvalRunResult, QueryMode, RefreshRequest, dump_model


def keyword_recall(text: str, expected_keywords: list[str]) -> float:
    lowered = text.lower()
    matches = sum(1 for keyword in expected_keywords if keyword.lower() in lowered)
    return matches / max(len(expected_keywords), 1)


def metric(name: str, value: float, **details) -> EvalMetric:
    return EvalMetric(name=name, value=value, details=details)


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def slot_recall(text: str, expected_slots: dict[str, list[str]]) -> tuple[float, dict[str, float]]:
    lowered = _normalized_text(text)
    per_slot: dict[str, float] = {}
    for slot_name, expected_values in expected_slots.items():
        normalized_values = [_normalized_text(value) for value in expected_values]
        per_slot[slot_name] = 1.0 if all(value in lowered for value in normalized_values) else 0.0
    average = statistics.fmean(per_slot.values()) if per_slot else 0.0
    return average, per_slot


def run_scenario(service: MemoryService, scenario_name: str) -> EvalRunResult:
    scenario = get_scenario(scenario_name)
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
    baseline_recall = keyword_recall(baseline.packed_context, scenario.expected_keywords)
    hierarchy_recall = keyword_recall(hierarchy.packed_context, scenario.expected_keywords)
    baseline_slot_recall, baseline_slot_map = slot_recall(baseline.packed_context, scenario.expected_slots)
    hierarchy_slot_recall, hierarchy_slot_map = slot_recall(hierarchy.packed_context, scenario.expected_slots)
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


def run_all() -> list[EvalRunResult]:
    results = []
    for scenario in all_scenarios():
        results.append(run_scenario(MemoryService(load_settings()), scenario.name))
    return results


def main() -> None:
    payload = [dump_model(result) for result in run_all()]
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
