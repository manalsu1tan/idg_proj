from __future__ import annotations

"""Counterfactual replay evaluation helpers
Runs base and variant scenario replays then reports retrieval and answer deltas"""

from dataclasses import replace
from typing import Callable

from packages.evals.scenarios import Scenario, ScenarioEvent, get_scenario, scenario_timestamp
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings
from packages.schemas.models import (
    BuildSummariesRequest,
    CounterfactualDiff,
    CounterfactualOperation,
    CounterfactualReplayRequest,
    CounterfactualReplayResponse,
    CounterfactualSnapshot,
    CounterfactualVariantRequest,
    CounterfactualVariantResult,
    MemoryNode,
)


def _resolve_scenario(name: str, seed: int | None) -> Scenario:
    if seed is None:
        return get_scenario(name)
    return get_scenario(name, seeds=(seed,))


def _matching_event_index(events: list[ScenarioEvent], match_text: str) -> int:
    matches = [index for index, event in enumerate(events) if event.text == match_text]
    if not matches:
        raise ValueError(f"No scenario event matched text: {match_text!r}")
    if len(matches) > 1:
        raise ValueError(f"Multiple scenario events matched text: {match_text!r}")
    return matches[0]


def apply_counterfactual_operation(scenario: Scenario, operation: CounterfactualOperation) -> Scenario:
    """Apply one counterfactual operation to a scenario."""
    events = list(scenario.events)
    if operation.op == "replace_event_text":
        if not operation.match_text or operation.new_text is None:
            raise ValueError("replace_event_text requires match_text and new_text.")
        index = _matching_event_index(events, operation.match_text)
        original = events[index]
        events[index] = ScenarioEvent(text=operation.new_text, day_offset=original.day_offset, importance=original.importance)
        return replace(scenario, events=events)

    if operation.op == "remove_event":
        if not operation.match_text:
            raise ValueError("remove_event requires match_text.")
        index = _matching_event_index(events, operation.match_text)
        del events[index]
        return replace(scenario, events=events)

    if operation.op == "insert_event_after_day":
        if operation.after_day_offset is None or operation.text is None:
            raise ValueError("insert_event_after_day requires after_day_offset and text.")
        events.append(
            ScenarioEvent(
                text=operation.text,
                day_offset=operation.after_day_offset + 1,
                importance=float(operation.importance_score if operation.importance_score is not None else 0.5),
            )
        )
        return replace(scenario, events=sorted(events, key=lambda item: item.day_offset))

    if operation.op == "change_importance":
        if not operation.match_text or operation.importance_score is None:
            raise ValueError("change_importance requires match_text and importance_score.")
        index = _matching_event_index(events, operation.match_text)
        original = events[index]
        events[index] = ScenarioEvent(text=original.text, day_offset=original.day_offset, importance=float(operation.importance_score))
        return replace(scenario, events=events)

    raise ValueError(f"Unsupported counterfactual op: {operation.op}")


def apply_counterfactual_variant(scenario: Scenario, variant: CounterfactualVariantRequest) -> Scenario:
    """Apply a sequence of counterfactual operations to a scenario."""
    updated = scenario
    for operation in variant.operations:
        updated = apply_counterfactual_operation(updated, operation)
    return replace(
        updated,
        name=f"{scenario.name}__cf_{variant.variant_id}",
        agent_id=f"{scenario.agent_id}-cf-{variant.variant_id}",
    )


def _node_signature(node: MemoryNode) -> str:
    return f"[{node.level.value}/{node.node_type.value}] {node.text}"


def _snapshot_for_scenario(
    scenario: Scenario,
    *,
    query_override: str | None,
    token_budget: int,
    mode,
    branch_limit: int,
    generate_answer: bool,
    service_factory: Callable[[], MemoryService],
) -> CounterfactualSnapshot:
    service = service_factory()
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
    query = query_override or scenario.query
    response = service.retrieve(
        agent_id=scenario.agent_id,
        query=query,
        query_time=scenario_timestamp(scenario.query_day_offset),
        mode=mode,
        token_budget=token_budget,
        branch_limit=branch_limit,
        generate_answer=generate_answer,
        verify_answer=False,
    )
    return CounterfactualSnapshot(
        retrieval_depth=response.retrieval_depth,
        retrieved_token_count=response.diagnostics.retrieved_token_count,
        packed_token_count=response.diagnostics.packed_token_count,
        branch_count=response.diagnostics.branch_count,
        summary_count=len(built),
        retrieved_signatures=[_node_signature(item.node) for item in response.retrieved_nodes],
        packed_context=response.packed_context,
        answer_text=response.answer.text if response.answer else "",
        answer_confidence=response.answer.confidence if response.answer else 0.0,
    )


def _diff_snapshots(base: CounterfactualSnapshot, variant: CounterfactualSnapshot) -> CounterfactualDiff:
    base_set = set(base.retrieved_signatures)
    variant_set = set(variant.retrieved_signatures)
    return CounterfactualDiff(
        answer_changed=base.answer_text.strip() != variant.answer_text.strip(),
        retrieval_depth_delta=variant.retrieval_depth - base.retrieval_depth,
        retrieved_token_delta=variant.retrieved_token_count - base.retrieved_token_count,
        packed_token_delta=variant.packed_token_count - base.packed_token_count,
        branch_count_delta=variant.branch_count - base.branch_count,
        summary_count_delta=variant.summary_count - base.summary_count,
        added_retrieved_signatures=sorted(variant_set - base_set),
        removed_retrieved_signatures=sorted(base_set - variant_set),
    )


def render_counterfactual_markdown(report: CounterfactualReplayResponse) -> str:
    """Render a markdown report for counterfactual replay output."""
    lines = [
        "# Counterfactual Replay Report",
        "",
        f"Scenario: `{report.scenario_name}`",
        f"Seed: `{report.seed}`" if report.seed is not None else "Seed: `default`",
        f"Query: {report.query}",
        f"Mode: `{report.mode.value}`",
        f"Token budget: `{report.token_budget}`",
        f"Branch limit: `{report.branch_limit}`",
        "",
        "## Base Snapshot",
        "",
        f"- Retrieval depth: {report.base.retrieval_depth}",
        f"- Retrieved tokens: {report.base.retrieved_token_count}",
        f"- Packed tokens: {report.base.packed_token_count}",
        f"- Branch count: {report.base.branch_count}",
        f"- Summary count: {report.base.summary_count}",
        f"- Answer confidence: {report.base.answer_confidence:.3f}",
        "",
        "### Base Retrieved Signatures",
        "",
    ]
    if report.base.retrieved_signatures:
        lines.extend([f"- {signature}" for signature in report.base.retrieved_signatures])
    else:
        lines.append("- No retrieved nodes.")

    for variant in report.variants:
        lines.extend(
            [
                "",
                f"## Variant `{variant.variant_id}`",
                "",
                variant.description or "No description provided.",
                "",
                f"- Retrieval depth delta: {variant.diff.retrieval_depth_delta}",
                f"- Retrieved token delta: {variant.diff.retrieved_token_delta}",
                f"- Packed token delta: {variant.diff.packed_token_delta}",
                f"- Branch count delta: {variant.diff.branch_count_delta}",
                f"- Summary count delta: {variant.diff.summary_count_delta}",
                f"- Answer changed: {'yes' if variant.diff.answer_changed else 'no'}",
                "",
                "### Added Retrieved Signatures",
                "",
            ]
        )
        if variant.diff.added_retrieved_signatures:
            lines.extend([f"- {signature}" for signature in variant.diff.added_retrieved_signatures])
        else:
            lines.append("- None.")
        lines.extend(["", "### Removed Retrieved Signatures", ""])
        if variant.diff.removed_retrieved_signatures:
            lines.extend([f"- {signature}" for signature in variant.diff.removed_retrieved_signatures])
        else:
            lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def run_counterfactual_replay(
    request: CounterfactualReplayRequest,
    *,
    service_factory: Callable[[], MemoryService] | None = None,
) -> CounterfactualReplayResponse:
    """Run base and variant scenario replays, then compute deltas."""
    scenario = _resolve_scenario(request.scenario_name, request.seed)
    service_factory = service_factory or (lambda: MemoryService(load_settings()))
    base_snapshot = _snapshot_for_scenario(
        scenario,
        query_override=request.query_override,
        token_budget=request.token_budget,
        mode=request.mode,
        branch_limit=request.branch_limit,
        generate_answer=request.generate_answer,
        service_factory=service_factory,
    )
    variants: list[CounterfactualVariantResult] = []
    for variant_request in request.variants:
        variant_scenario = apply_counterfactual_variant(scenario, variant_request)
        variant_snapshot = _snapshot_for_scenario(
            variant_scenario,
            query_override=request.query_override,
            token_budget=request.token_budget,
            mode=request.mode,
            branch_limit=request.branch_limit,
            generate_answer=request.generate_answer,
            service_factory=service_factory,
        )
        variants.append(
            CounterfactualVariantResult(
                variant_id=variant_request.variant_id,
                description=variant_request.description,
                operations=variant_request.operations,
                snapshot=variant_snapshot,
                diff=_diff_snapshots(base_snapshot, variant_snapshot),
            )
        )

    report = CounterfactualReplayResponse(
        scenario_name=scenario.name,
        seed=scenario.seed,
        query=request.query_override or scenario.query,
        mode=request.mode,
        token_budget=request.token_budget,
        branch_limit=request.branch_limit,
        base=base_snapshot,
        variants=variants,
    )
    report.markdown = render_counterfactual_markdown(report)
    return report
