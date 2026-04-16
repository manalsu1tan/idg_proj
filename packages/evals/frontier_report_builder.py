from __future__ import annotations

"""Frontier report payload and markdown builder
Formats sweep metrics for downstream review"""

import statistics
from datetime import datetime, timezone
from typing import Any, Callable


def render_frontier_markdown(
    *,
    exported_at: str,
    slices: list[Any],
    candidates: list[Any],
    frontier: list[Any],
    dimensions: list[Any],
    sample_method: str,
    family_objectives: list[Any],
    random_seeds: tuple[int, ...],
    stability_report: dict[str, Any] | None = None,
) -> str:
    """Render frontier sweep payload as markdown
    Formats slices dimensions frontier rows top candidates and stability tables"""
    lines = [
        "# Frontier Sweep Report",
        "",
        f"Generated: {exported_at}",
        f"Sampling method: {sample_method}",
        f"Optimization random seeds: {','.join(str(seed) for seed in random_seeds)}",
        f"Candidates evaluated: {len(candidates)}",
        f"Frontier size: {len(frontier)}",
        "",
        "## Objective Slices",
        "",
        "| Slice | Weight | Seeds | Perturbations |",
        "| --- | ---: | --- | --- |",
    ]
    for slice_cfg in slices:
        lines.append(
            "| {name} | {weight:.3f} | {seeds} | {styles} |".format(
                name=slice_cfg.name,
                weight=slice_cfg.weight,
                seeds=",".join(str(seed) for seed in slice_cfg.seeds),
                styles=",".join(slice_cfg.perturbation_styles) if slice_cfg.perturbation_styles else "-",
            )
        )

    lines.extend(["", "## Sweep Dimensions", ""])
    for dimension in dimensions:
        lines.append(
            f"- `{dimension.key}`: [{dimension.min_value:g}, {dimension.max_value:g}] ({dimension.value_type})"
        )

    if family_objectives:
        lines.extend(["", "## Family Objectives", ""])
        for objective in family_objectives:
            lines.append(f"- `{objective.family}:{objective.metric}:{objective.direction}`")

    lines.extend(
        [
            "",
            "## Pareto Frontier",
            "",
            "| Candidate | Utility | Slot Gain | Keyword Gain | Win Rate | Token Delta |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in frontier:
        slot_ci = row.objective_seed_statistics.get("global.slot_gain", {})
        token_ci = row.objective_seed_statistics.get("global.token_delta", {})
        slot_ci_text = f"[{slot_ci.get('ci95_low', 0.0):.3f}, {slot_ci.get('ci95_high', 0.0):.3f}]"
        token_ci_text = f"[{token_ci.get('ci95_low', 0.0):.3f}, {token_ci.get('ci95_high', 0.0):.3f}]"
        lines.append(
            "| {candidate} | {utility:.3f} | {slot_gain:.3f} {slot_ci} | {kw_gain:.3f} | {win_rate:.3f} | {token_delta:.3f} {token_ci} |".format(
                candidate=row.candidate_id,
                utility=row.utility_score,
                slot_gain=row.objective_vector.get("global.slot_gain", 0.0),
                slot_ci=slot_ci_text,
                kw_gain=row.objective_vector.get("global.keyword_gain", 0.0),
                win_rate=row.objective_vector.get("global.hierarchy_win_rate", 0.0),
                token_delta=row.objective_vector.get("global.token_delta", 0.0),
                token_ci=token_ci_text,
            )
        )

    lines.extend(
        [
            "",
            "## Top Candidates",
            "",
            "| Candidate | Frontier | Utility | Worst Slot Gain | Worst Keyword Gain | Flat Win Penalty |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    frontier_ids = {item.candidate_id for item in frontier}
    for row in candidates[: min(25, len(candidates))]:
        lines.append(
            "| {candidate} | {is_frontier} | {utility:.3f} | {worst_slot:.3f} | {worst_kw:.3f} | {flat_penalty:.3f} |".format(
                candidate=row.candidate_id,
                is_frontier="yes" if row.candidate_id in frontier_ids else "no",
                utility=row.utility_score,
                worst_slot=row.objective_vector.get("robust.worst_slot_gain", 0.0),
                worst_kw=row.objective_vector.get("robust.worst_keyword_gain", 0.0),
                flat_penalty=row.objective_vector.get("global.flat_win_penalty", 0.0),
            )
        )

    if stability_report:
        lines.extend(["", "## Stability Report", ""])
        lines.append(f"- Mode count across runs: {stability_report.get('mode_count', 0)}")
        lines.append(
            "- Average pairwise mode Jaccard: "
            f"{float(stability_report.get('average_pairwise_mode_jaccard', 0.0)):.3f}"
        )
        lines.extend(
            [
                "",
                "| Mode | Appearance Rate | Run Count | Candidate Occurrences | Slot Gain Range | Token Delta Range |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for mode in stability_report.get("modes", []):
            movement = mode.get("metric_movement", {})
            slot_range = movement.get("global.slot_gain", {}).get("range", 0.0)
            token_range = movement.get("global.token_delta", {}).get("range", 0.0)
            lines.append(
                "| {mode_id} | {appearance_rate:.3f} | {run_count} | {occurrences} | {slot_range:.4f} | {token_range:.4f} |".format(
                    mode_id=mode.get("mode_id", "-"),
                    appearance_rate=float(mode.get("appearance_rate", 0.0)),
                    run_count=len(mode.get("run_indices", [])),
                    occurrences=int(mode.get("candidate_occurrence_count", 0)),
                    slot_range=float(slot_range),
                    token_range=float(token_range),
                )
            )
    return "\n".join(lines).rstrip() + "\n"


def build_frontier_report_payload(
    *,
    runs: list[Any],
    slices: list[Any],
    dimensions: list[Any],
    families: tuple[str, ...] | None,
    family_objectives: list[Any],
    sample_method: str,
    max_candidates: int,
    deduped_run_seeds: tuple[int, ...],
    use_quick_scenarios: bool,
    scenario_limit: int | None,
    pareto_epsilon: float,
    mode_match_threshold: float,
    stability_report: dict[str, Any],
    assignment_lookup: dict[tuple[int, str], str],
    candidate_payload_builder: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Build export payload from sweep runs
    Computes global summary run details stability assignment and candidate payloads"""
    primary_run = runs[0]
    evaluated = primary_run.candidates
    frontier_rows = primary_run.frontier
    exported_at = datetime.now(timezone.utc).isoformat()
    primary_frontier_ids = {item.candidate_id for item in frontier_rows}

    payload = {
        "exported_at": exported_at,
        "report_type": "frontier_sweep_report",
        "summary": {
            "candidate_count": len(evaluated),
            "frontier_count": len(frontier_rows),
            "sample_method": sample_method,
            "max_candidates_requested": max_candidates,
            "random_seed": primary_run.random_seed,
            "optimization_run_count": len(runs),
            "optimization_random_seeds": list(deduped_run_seeds),
            "quick_scenarios": use_quick_scenarios,
            "scenario_limit": scenario_limit,
            "pareto_epsilon": pareto_epsilon,
            "mode_match_threshold": mode_match_threshold,
            "slice_names": [item.name for item in slices],
            "families": list(families) if families else None,
            "objective_key_count": len({key for item in evaluated for key in item.objective_vector.keys()}),
            "global_slot_gain_mean": statistics.fmean(item.objective_vector.get("global.slot_gain", 0.0) for item in evaluated)
            if evaluated
            else 0.0,
            "global_keyword_gain_mean": statistics.fmean(item.objective_vector.get("global.keyword_gain", 0.0) for item in evaluated)
            if evaluated
            else 0.0,
            "global_token_delta_mean": statistics.fmean(item.objective_vector.get("global.token_delta", 0.0) for item in evaluated)
            if evaluated
            else 0.0,
        },
        "slices": [
            {
                "name": item.name,
                "weight": item.weight,
                "seeds": list(item.seeds),
                "perturbation_styles": list(item.perturbation_styles),
            }
            for item in slices
        ],
        "dimensions": [
            {
                "key": item.key,
                "min": item.min_value,
                "max": item.max_value,
                "type": item.value_type,
            }
            for item in dimensions
        ],
        "family_objectives": [
            {"family": item.family, "metric": item.metric, "direction": item.direction}
            for item in family_objectives
        ],
        "frontier_candidate_ids": [item.candidate_id for item in frontier_rows],
        "stability_report": stability_report,
        "optimization_runs": [
            {
                "run_index": run_index,
                "random_seed": run.random_seed,
                "candidate_count": len(run.candidates),
                "frontier_count": len(run.frontier),
                "frontier_candidate_ids": [item.candidate_id for item in run.frontier],
                "frontier_candidates": [
                    candidate_payload_builder(
                        item,
                        is_frontier=True,
                        mode_id=assignment_lookup.get((run_index, item.candidate_id)),
                    )
                    for item in run.frontier
                ],
            }
            for run_index, run in enumerate(runs)
        ],
        "candidates": [
            candidate_payload_builder(
                item,
                is_frontier=item.candidate_id in primary_frontier_ids,
                mode_id=assignment_lookup.get((0, item.candidate_id)),
            )
            for item in evaluated
        ],
    }
    payload["markdown"] = render_frontier_markdown(
        exported_at=exported_at,
        slices=slices,
        candidates=evaluated,
        frontier=frontier_rows,
        dimensions=dimensions,
        sample_method=sample_method,
        family_objectives=family_objectives,
        random_seeds=deduped_run_seeds,
        stability_report=stability_report if len(runs) > 1 else None,
    )
    return payload
