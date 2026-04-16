from __future__ import annotations

"""Frontier sweep cli and orchestration
Runs candidate sampling scoring and report export"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
import os
import random
import statistics
import tempfile
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from packages.evals.report import REPORTS_DIR, build_report_payload
from packages.evals.frontier_report_builder import build_frontier_report_payload
from packages.evals.runner import run_scenario_instance
from packages.evals.scenarios import (
    DEFAULT_SCENARIO_SEEDS,
    QUERY_PERTURBATION_STYLES,
    all_scenarios,
    quick_scenarios,
    scenario_with_perturbation,
)
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import QUERY_ROUTING_POLICY_PATH, load_query_routing_policy, load_settings
from packages.schemas.models import dump_model


DEFAULT_SWEEP_SPACE: dict[str, dict[str, float | str]] = {
    # Strategy thresholds
    "strategy_thresholds.feature_active_min": {"min": 0.24, "max": 0.44, "type": "float"},
    "strategy_thresholds.coverage_min": {"min": 0.34, "max": 0.58, "type": "float"},
    "strategy_thresholds.hierarchy_expand_min": {"min": 0.38, "max": 0.62, "type": "float"},
    "strategy_thresholds.revision_leaf_min": {"min": 0.34, "max": 0.58, "type": "float"},
    "strategy_thresholds.multi_branch_min": {"min": 0.52, "max": 0.78, "type": "float"},
    # Resolver thresholds
    "resolver_thresholds.low_confidence_margin": {"min": 0.04, "max": 0.16, "type": "float"},
    "resolver_thresholds.disambiguation_close_margin": {"min": 0.04, "max": 0.16, "type": "float"},
    "resolver_thresholds.competing_person_score_ratio": {"min": 0.45, "max": 0.75, "type": "float"},
    "resolver_thresholds.competing_person_score_gap": {"min": 0.10, "max": 0.40, "type": "float"},
    "resolver_thresholds.competing_person_window": {"min": 4, "max": 12, "type": "int"},
    "resolver_thresholds.expansion_branch_target": {"min": 2, "max": 4, "type": "int"},
    # Supplemental utility gate thresholds
    "supplemental_thresholds.base_utility_threshold": {"min": 0.03, "max": 0.14, "type": "float"},
    "supplemental_thresholds.missing_required_relax": {"min": 0.00, "max": 0.05, "type": "float"},
    "supplemental_thresholds.communication_gap_relax": {"min": 0.00, "max": 0.05, "type": "float"},
    "supplemental_thresholds.polarity_relax": {"min": 0.00, "max": 0.05, "type": "float"},
    "supplemental_thresholds.disambiguation_relax": {"min": 0.00, "max": 0.07, "type": "float"},
    "supplemental_thresholds.low_confidence_relax": {"min": 0.00, "max": 0.03, "type": "float"},
    "supplemental_thresholds.temporal_only_penalty": {"min": 0.00, "max": 0.08, "type": "float"},
    "supplemental_thresholds.min_utility_threshold": {"min": 0.01, "max": 0.08, "type": "float"},
    "supplemental_thresholds.max_utility_threshold": {"min": 0.10, "max": 0.24, "type": "float"},
    # Supplemental utility bonuses
    "supplemental_weights.coverage_bonus_per_key": {"min": 0.02, "max": 0.12, "type": "float"},
    "supplemental_weights.required_bonus_per_key": {"min": 0.06, "max": 0.22, "type": "float"},
    "supplemental_weights.communication_bonus": {"min": 0.04, "max": 0.18, "type": "float"},
    "supplemental_weights.polarity_bonus": {"min": 0.04, "max": 0.18, "type": "float"},
    "supplemental_weights.disambiguation_bonus": {"min": 0.04, "max": 0.18, "type": "float"},
    "supplemental_weights.entity_aligned_bonus": {"min": 0.00, "max": 0.08, "type": "float"},
}

DEFAULT_FAMILY_OBJECTIVES: tuple[str, ...] = (
    "multi_person_interference:slot_gain:max",
    "time_window_pressure:token_delta:max",
)

DEFAULT_HARD_PERTURBATION_STYLES: tuple[str, ...] = (
    "concise",
    "indirect",
    "typo_noise",
)

CHECKPOINT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class SweepDimension:
    key: str
    min_value: float
    max_value: float
    value_type: str  # float | int


@dataclass(frozen=True)
class EvalSlice:
    name: str
    seeds: tuple[int, ...]
    perturbation_styles: tuple[str, ...]
    weight: float


@dataclass(frozen=True)
class FamilyObjective:
    family: str
    metric: str
    direction: str  # max | min


@dataclass(frozen=True)
class CandidateResult:
    candidate_id: str
    overrides: dict[str, float]
    objective_vector: dict[str, float]
    utility_score: float
    slice_summaries: dict[str, dict[str, float]]
    family_slice_metrics: dict[str, dict[str, dict[str, float]]]
    slice_seed_statistics: dict[str, dict[str, dict[str, Any]]]
    objective_seed_statistics: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class SweepRunResult:
    random_seed: int
    candidates: list[CandidateResult]
    frontier: list[CandidateResult]


SEED_SUMMARY_METRIC_KEYS: tuple[str, ...] = (
    "avg_slot_recall_gain",
    "avg_keyword_recall_gain",
    "hierarchy_win_rate",
    "flat_win_rate",
    "tie_rate",
    "avg_retrieved_token_delta",
    "avg_slot_recall_per_token_gain",
)


OBJECTIVE_FROM_SLICE_METRIC: dict[str, str] = {
    "global.slot_gain": "avg_slot_recall_gain",
    "global.keyword_gain": "avg_keyword_recall_gain",
    "global.hierarchy_win_rate": "hierarchy_win_rate",
    "global.token_delta": "avg_retrieved_token_delta",
    "global.slot_per_token_gain": "avg_slot_recall_per_token_gain",
}


STABILITY_FEATURE_KEYS: tuple[str, ...] = (
    "global.slot_gain",
    "global.keyword_gain",
    "global.hierarchy_win_rate",
    "global.token_delta",
    "family.multi_person_interference.slot_gain.max",
)


def _log(message: str, *, enabled: bool = True) -> None:
    if not enabled:
        return
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[frontier {timestamp}] {message}", flush=True)


def _set_nested_value(payload: dict[str, Any], dotted_key: str, value: float | int) -> None:
    keys = dotted_key.split(".")
    current = payload
    for key in keys[:-1]:
        nested = current.get(key)
        if not isinstance(nested, dict):
            nested = {}
            current[key] = nested
        current = nested
    current[keys[-1]] = value


def _apply_overrides(base_policy: dict[str, Any], overrides: dict[str, float]) -> dict[str, Any]:
    policy = deepcopy(base_policy)
    for dotted_key, value in overrides.items():
        _set_nested_value(policy, dotted_key, value)
    return policy


def _dimension_from_spec(key: str, spec: Any) -> SweepDimension:
    if isinstance(spec, dict):
        if "min" not in spec or "max" not in spec:
            raise ValueError(f"Sweep-space entry for {key!r} must contain min/max.")
        min_value = float(spec["min"])
        max_value = float(spec["max"])
        value_type = str(spec.get("type", "float"))
    elif isinstance(spec, list) and spec:
        min_value = min(float(item) for item in spec)
        max_value = max(float(item) for item in spec)
        all_int = all(float(item).is_integer() for item in spec)
        value_type = "int" if all_int else "float"
    else:
        raise ValueError(f"Unsupported sweep-space spec for {key!r}.")
    if value_type not in {"float", "int"}:
        raise ValueError(f"Unsupported type for sweep-space entry {key!r}: {value_type!r}")
    if max_value < min_value:
        raise ValueError(f"Invalid range for {key!r}: max < min")
    return SweepDimension(key=key, min_value=min_value, max_value=max_value, value_type=value_type)


def _load_sweep_space(path: Path | None) -> list[SweepDimension]:
    if path is None:
        payload: dict[str, Any] = DEFAULT_SWEEP_SPACE
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Sweep space must be a JSON object.")
    dimensions = [_dimension_from_spec(key, spec) for key, spec in payload.items()]
    return sorted(dimensions, key=lambda item: item.key)


def _quantize_value(dimension: SweepDimension, raw_value: float) -> float:
    clipped = min(dimension.max_value, max(dimension.min_value, raw_value))
    if dimension.value_type == "int":
        return float(int(round(clipped)))
    return round(clipped, 6)


def _sample_overrides_lhs(dimensions: list[SweepDimension], count: int, rng: random.Random) -> list[dict[str, float]]:
    if count <= 0:
        return []
    samples = [{} for _ in range(count)]
    for dimension in dimensions:
        bins = list(range(count))
        rng.shuffle(bins)
        for index in range(count):
            unit = (bins[index] + rng.random()) / count
            raw_value = dimension.min_value + unit * (dimension.max_value - dimension.min_value)
            samples[index][dimension.key] = _quantize_value(dimension, raw_value)
    return samples


def _sample_overrides_random(dimensions: list[SweepDimension], count: int, rng: random.Random) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    for _ in range(max(0, count)):
        sample: dict[str, float] = {}
        for dimension in dimensions:
            raw_value = rng.uniform(dimension.min_value, dimension.max_value)
            sample[dimension.key] = _quantize_value(dimension, raw_value)
        samples.append(sample)
    return samples


def _sample_overrides(
    dimensions: list[SweepDimension],
    *,
    max_candidates: int,
    sample_method: str,
    rng: random.Random,
) -> list[dict[str, float]]:
    if max_candidates <= 0:
        return []
    if sample_method == "lhs":
        sampled = _sample_overrides_lhs(dimensions, max_candidates, rng)
    elif sample_method == "random":
        sampled = _sample_overrides_random(dimensions, max_candidates, rng)
    else:
        raise ValueError(f"Unsupported sample method: {sample_method}")

    # De-duplicate in case quantization collapses points.
    unique: list[dict[str, float]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for item in sampled:
        signature = tuple(sorted(item.items()))
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(item)
    return unique


def _metric_alias(metric: str) -> str:
    aliases = {
        "slot_gain": "avg_slot_recall_gain",
        "keyword_gain": "avg_keyword_recall_gain",
        "token_delta": "avg_retrieved_token_delta",
        "win_rate": "hierarchy_win_rate",
        "hierarchy_win_rate": "hierarchy_win_rate",
        "flat_win_rate": "flat_win_rate",
        "tie_rate": "tie_rate",
    }
    return aliases.get(metric, metric)


def _parse_family_objective(raw: str) -> FamilyObjective:
    parts = [part.strip() for part in raw.split(":") if part.strip()]
    if len(parts) == 2:
        family, metric = parts
        direction = "max"
    elif len(parts) == 3:
        family, metric, direction = parts
    else:
        raise ValueError(f"Invalid family objective {raw!r}; expected family:metric[:max|min].")
    if direction not in {"max", "min"}:
        raise ValueError(f"Invalid direction {direction!r} in family objective {raw!r}.")
    return FamilyObjective(family=family, metric=metric, direction=direction)


def _build_slices(
    *,
    seeds: tuple[int, ...],
    include_unseen_slice: bool,
    unseen_offsets: tuple[int, ...],
    include_perturbation_slice: bool,
    perturbation_styles: tuple[str, ...],
    canonical_weight: float,
    unseen_weight: float,
    perturbation_weight: float,
) -> list[EvalSlice]:
    slices: list[EvalSlice] = [EvalSlice(name="canonical", seeds=seeds, perturbation_styles=(), weight=canonical_weight)]

    if include_unseen_slice:
        unseen_seeds = sorted({seed + offset for seed in seeds for offset in unseen_offsets})
        slices.append(
            EvalSlice(
                name="unseen_seeds",
                seeds=tuple(unseen_seeds),
                perturbation_styles=(),
                weight=unseen_weight,
            )
        )

    if include_perturbation_slice:
        styles = tuple(dict.fromkeys(perturbation_styles))
        slices.append(
            EvalSlice(
                name="hard_perturbations",
                seeds=seeds,
                perturbation_styles=styles,
                weight=perturbation_weight,
            )
        )

    positive = [item for item in slices if item.weight > 0]
    if not positive:
        raise ValueError("At least one active slice must have weight > 0.")
    weight_sum = sum(item.weight for item in positive)
    normalized = [
        EvalSlice(
            name=item.name,
            seeds=item.seeds,
            perturbation_styles=item.perturbation_styles,
            weight=item.weight / weight_sum,
        )
        for item in positive
    ]
    return normalized


def _scenarios_for_slice(
    slice_cfg: EvalSlice,
    families: tuple[str, ...] | None,
    *,
    use_quick_scenarios: bool = False,
    scenario_limit: int | None = None,
) -> list[Any]:
    scenarios = quick_scenarios(seeds=slice_cfg.seeds) if use_quick_scenarios else all_scenarios(seeds=slice_cfg.seeds)
    if families:
        family_filter = set(families)
        scenarios = [scenario for scenario in scenarios if scenario.family_name in family_filter]
    if slice_cfg.perturbation_styles:
        scenarios = [
            scenario_with_perturbation(scenario, style)
            for scenario in scenarios
            for style in slice_cfg.perturbation_styles
        ]
    if scenario_limit and scenario_limit > 0:
        scenarios = scenarios[:scenario_limit]
    return scenarios


def _slice_report(
    *,
    service: MemoryService,
    slice_cfg: EvalSlice,
    families: tuple[str, ...] | None,
    use_quick_scenarios: bool = False,
    scenario_limit: int | None = None,
    log_progress: bool = False,
    log_every_scenarios: int = 0,
    log_prefix: str = "",
) -> dict[str, Any]:
    scenarios = _scenarios_for_slice(
        slice_cfg,
        families,
        use_quick_scenarios=use_quick_scenarios,
        scenario_limit=scenario_limit,
    )
    total_scenarios = len(scenarios)
    slice_started = time.monotonic()
    prefix = f"{log_prefix} " if log_prefix else ""
    _log(
        f"{prefix}slice={slice_cfg.name}: running {total_scenarios} scenarios.",
        enabled=log_progress,
    )

    run_results = []
    skipped_invalid_prompt: list[dict[str, Any]] = []
    interval = max(1, int(log_every_scenarios))
    for index, scenario in enumerate(scenarios, start=1):
        try:
            run_results.append(run_scenario_instance(service, scenario))
        except RuntimeError as exc:
            error_text = str(exc)
            lowered = error_text.lower()
            if "invalid_prompt" in lowered or "flagged as potentially violating our usage policy" in lowered:
                skipped_invalid_prompt.append(
                    {
                        "scenario_name": scenario.name,
                        "seed": scenario.seed,
                        "family_name": scenario.family_name,
                        "error": error_text,
                    }
                )
                _log(
                    (
                        f"{prefix}slice={slice_cfg.name}: scenario {index}/{total_scenarios} "
                        f"({scenario.name}) skipped due to invalid_prompt."
                    ),
                    enabled=True,
                )
                continue
            raise
        if log_progress and log_every_scenarios > 0 and (index == 1 or index == total_scenarios or index % interval == 0):
            elapsed = time.monotonic() - slice_started
            rate = index / elapsed if elapsed > 0 else 0.0
            remaining = total_scenarios - index
            eta_seconds = (remaining / rate) if rate > 0 else 0.0
            _log(
                (
                    f"{prefix}slice={slice_cfg.name}: scenario {index}/{total_scenarios} "
                    f"({scenario.name}) complete; elapsed={elapsed/60.0:.1f}m; ETA={eta_seconds/60.0:.1f}m."
                ),
                enabled=True,
            )

    _log(
        f"{prefix}slice={slice_cfg.name}: completed in {(time.monotonic() - slice_started)/60.0:.1f}m.",
        enabled=log_progress,
    )
    payload = build_report_payload([dump_model(result) for result in run_results])
    if skipped_invalid_prompt:
        payload["skipped_scenarios"] = skipped_invalid_prompt
        summary = payload.get("summary", {})
        if isinstance(summary, dict):
            summary["skipped_invalid_prompt_count"] = len(skipped_invalid_prompt)
            payload["summary"] = summary
        _log(
            (
                f"{prefix}slice={slice_cfg.name}: skipped {len(skipped_invalid_prompt)} scenario(s) "
                "due to invalid_prompt."
            ),
            enabled=True,
        )
    return payload


def _weighted_average(values: list[tuple[float, float]]) -> float:
    if not values:
        return 0.0
    denom = sum(weight for _, weight in values)
    if denom <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / denom


def _sample_stddev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _seed_stat_summary(seed_values: list[tuple[int, float]]) -> dict[str, Any]:
    ordered = sorted(seed_values, key=lambda item: item[0])
    values = [value for _, value in ordered]
    count = len(values)
    mean_value = statistics.fmean(values) if values else 0.0
    stddev = _sample_stddev(values)
    stderr = (stddev / math.sqrt(count)) if count > 0 else 0.0
    ci_half_width = 1.96 * stderr
    return {
        "seed_count": count,
        "mean": mean_value,
        "stddev": stddev,
        "stderr": stderr,
        "ci95_low": mean_value - ci_half_width,
        "ci95_high": mean_value + ci_half_width,
        "min": min(values) if values else 0.0,
        "max": max(values) if values else 0.0,
        "by_seed": [{"seed": seed, "value": value} for seed, value in ordered],
    }


def _slice_seed_statistics(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scenarios = payload.get("scenarios", [])
    if not isinstance(scenarios, list) or not scenarios:
        return {metric: _seed_stat_summary([]) for metric in SEED_SUMMARY_METRIC_KEYS}

    per_seed: dict[int, dict[str, list[float]]] = {}
    for row in scenarios:
        if not isinstance(row, dict):
            continue
        seed_value = row.get("seed")
        if not isinstance(seed_value, int):
            continue
        deltas = row.get("deltas", {}) if isinstance(row.get("deltas"), dict) else {}
        baseline = row.get("baseline", {}) if isinstance(row.get("baseline"), dict) else {}
        hierarchy = row.get("hierarchy", {}) if isinstance(row.get("hierarchy"), dict) else {}
        winner = str(row.get("winner", "tie"))
        seed_bucket = per_seed.setdefault(seed_value, {metric: [] for metric in SEED_SUMMARY_METRIC_KEYS})
        seed_bucket["avg_slot_recall_gain"].append(float(deltas.get("slot_recall_gain", 0.0)))
        seed_bucket["avg_keyword_recall_gain"].append(float(deltas.get("keyword_recall_gain", 0.0)))
        seed_bucket["avg_retrieved_token_delta"].append(float(deltas.get("retrieved_token_count_delta", 0.0)))
        baseline_slot_per_token = float(baseline.get("slot_recall_per_token", 0.0))
        hierarchy_slot_per_token = float(hierarchy.get("slot_recall_per_token", 0.0))
        seed_bucket["avg_slot_recall_per_token_gain"].append(hierarchy_slot_per_token - baseline_slot_per_token)
        seed_bucket["hierarchy_win_rate"].append(1.0 if winner == "hierarchy" else 0.0)
        seed_bucket["flat_win_rate"].append(1.0 if winner == "flat" else 0.0)
        seed_bucket["tie_rate"].append(1.0 if winner == "tie" else 0.0)

    seed_metric_values: dict[str, list[tuple[int, float]]] = {metric: [] for metric in SEED_SUMMARY_METRIC_KEYS}
    for seed, metrics in per_seed.items():
        for metric_name in SEED_SUMMARY_METRIC_KEYS:
            values = metrics.get(metric_name, [])
            mean_value = statistics.fmean(values) if values else 0.0
            seed_metric_values[metric_name].append((seed, mean_value))

    return {metric: _seed_stat_summary(values) for metric, values in seed_metric_values.items()}


def _weighted_seed_objective_stats(
    *,
    slices: list[EvalSlice],
    slice_seed_stats: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    objective_stats: dict[str, dict[str, Any]] = {}
    for objective_key, summary_metric in OBJECTIVE_FROM_SLICE_METRIC.items():
        weighted_means: list[tuple[float, float]] = []
        weighted_stderr_squares = 0.0
        effective_seeds = 0
        for slice_cfg in slices:
            metric_stats = slice_seed_stats.get(slice_cfg.name, {}).get(summary_metric)
            if not metric_stats:
                continue
            mean_value = float(metric_stats.get("mean", 0.0))
            stderr = float(metric_stats.get("stderr", 0.0))
            weighted_means.append((mean_value, slice_cfg.weight))
            weighted_stderr_squares += (slice_cfg.weight * stderr) ** 2
            effective_seeds += int(metric_stats.get("seed_count", 0))

        mean_value = _weighted_average(weighted_means)
        stderr = math.sqrt(weighted_stderr_squares)
        ci_half_width = 1.96 * stderr
        objective_stats[objective_key] = {
            "seed_count_effective": effective_seeds,
            "mean": mean_value,
            "stderr": stderr,
            "ci95_low": mean_value - ci_half_width,
            "ci95_high": mean_value + ci_half_width,
        }

    # global.flat_win_penalty derives from flat win rate with negated sign.
    flat_stats = objective_stats.get("global.hierarchy_win_rate")
    flat_win_stats = None
    if slices:
        weighted_means = []
        weighted_stderr_squares = 0.0
        effective_seeds = 0
        for slice_cfg in slices:
            metric_stats = slice_seed_stats.get(slice_cfg.name, {}).get("flat_win_rate")
            if not metric_stats:
                continue
            weighted_means.append((float(metric_stats.get("mean", 0.0)), slice_cfg.weight))
            weighted_stderr_squares += (slice_cfg.weight * float(metric_stats.get("stderr", 0.0))) ** 2
            effective_seeds += int(metric_stats.get("seed_count", 0))
        flat_mean = _weighted_average(weighted_means)
        flat_stderr = math.sqrt(weighted_stderr_squares)
        ci_half_width = 1.96 * flat_stderr
        flat_win_stats = {
            "seed_count_effective": effective_seeds,
            "mean": -flat_mean,
            "stderr": flat_stderr,
            "ci95_low": -(flat_mean + ci_half_width),
            "ci95_high": -(flat_mean - ci_half_width),
        }
    if flat_win_stats:
        objective_stats["global.flat_win_penalty"] = flat_win_stats
    elif flat_stats:
        objective_stats["global.flat_win_penalty"] = {
            "seed_count_effective": flat_stats.get("seed_count_effective", 0),
            "mean": 0.0,
            "stderr": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
        }

    return objective_stats


def _objective_name_for_family(obj: FamilyObjective) -> str:
    return f"family.{obj.family}.{obj.metric}.{obj.direction}"


def _evaluate_candidate(
    *,
    candidate_id: str,
    overrides: dict[str, float],
    base_policy: dict[str, Any],
    slices: list[EvalSlice],
    families: tuple[str, ...] | None,
    family_objectives: list[FamilyObjective],
    use_quick_scenarios: bool = False,
    scenario_limit: int | None = None,
    run_seed: int | None = None,
    log_progress: bool = False,
    log_every_scenarios: int = 0,
) -> CandidateResult:
    candidate_started = time.monotonic()
    run_prefix = f"run seed={run_seed}" if run_seed is not None else "run"
    _log(f"{run_prefix}: candidate={candidate_id} started.", enabled=log_progress)
    policy_payload = _apply_overrides(base_policy, overrides)
    with tempfile.TemporaryDirectory(prefix="frontier_policy_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        policy_path = tmp_path / f"{candidate_id}.json"
        db_path = tmp_path / f"{candidate_id}.db"
        policy_path.write_text(json.dumps(policy_payload, indent=2), encoding="utf-8")

        previous_policy_path = os.environ.get("PROJECT_QUERY_ROUTING_POLICY_PATH")
        previous_database_url = os.environ.get("PROJECT_DATABASE_URL")
        previous_auto_schema = os.environ.get("PROJECT_AUTO_CREATE_SCHEMA")
        try:
            os.environ["PROJECT_QUERY_ROUTING_POLICY_PATH"] = str(policy_path)
            os.environ["PROJECT_DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
            os.environ["PROJECT_AUTO_CREATE_SCHEMA"] = "true"
            service = MemoryService(load_settings())
            slice_reports = {}
            for slice_cfg in slices:
                slice_reports[slice_cfg.name] = _slice_report(
                    service=service,
                    slice_cfg=slice_cfg,
                    families=families,
                    use_quick_scenarios=use_quick_scenarios,
                    scenario_limit=scenario_limit,
                    log_progress=log_progress,
                    log_every_scenarios=log_every_scenarios,
                    log_prefix=f"{run_prefix} candidate={candidate_id}",
                )
        finally:
            if previous_policy_path is None:
                os.environ.pop("PROJECT_QUERY_ROUTING_POLICY_PATH", None)
            else:
                os.environ["PROJECT_QUERY_ROUTING_POLICY_PATH"] = previous_policy_path
            if previous_database_url is None:
                os.environ.pop("PROJECT_DATABASE_URL", None)
            else:
                os.environ["PROJECT_DATABASE_URL"] = previous_database_url
            if previous_auto_schema is None:
                os.environ.pop("PROJECT_AUTO_CREATE_SCHEMA", None)
            else:
                os.environ["PROJECT_AUTO_CREATE_SCHEMA"] = previous_auto_schema

    slice_summaries: dict[str, dict[str, float]] = {}
    slice_seed_statistics: dict[str, dict[str, dict[str, Any]]] = {}
    family_slice_metrics: dict[str, dict[str, dict[str, float]]] = {}
    for slice_cfg in slices:
        payload = slice_reports[slice_cfg.name]
        summary = payload.get("summary", {})
        slice_summaries[slice_cfg.name] = {
            "avg_slot_recall_gain": float(summary.get("avg_slot_recall_gain", 0.0)),
            "avg_keyword_recall_gain": float(summary.get("avg_keyword_recall_gain", 0.0)),
            "hierarchy_win_rate": float(summary.get("hierarchy_win_rate", 0.0)),
            "flat_win_rate": float(summary.get("flat_win_rate", 0.0)),
            "tie_rate": float(summary.get("tie_rate", 0.0)),
            "avg_retrieved_token_delta": float(summary.get("avg_retrieved_token_delta", 0.0)),
            "avg_slot_recall_per_token_gain": float(summary.get("avg_slot_recall_per_token_gain", 0.0)),
        }
        slice_seed_statistics[slice_cfg.name] = _slice_seed_statistics(payload)
        family_slice_metrics[slice_cfg.name] = {}
        for family_row in payload.get("families", []):
            family_name = family_row.get("family_name")
            if not isinstance(family_name, str):
                continue
            family_slice_metrics[slice_cfg.name][family_name] = {
                "avg_slot_recall_gain": float(family_row.get("avg_slot_recall_gain", 0.0)),
                "avg_keyword_recall_gain": float(family_row.get("avg_keyword_recall_gain", 0.0)),
                "avg_retrieved_token_delta": float(family_row.get("avg_retrieved_token_delta", 0.0)),
                "hierarchy_win_rate": float(family_row.get("hierarchy_win_rate", 0.0)),
                "flat_win_rate": float(family_row.get("flat_win_rate", 0.0)),
                "tie_rate": float(family_row.get("tie_rate", 0.0)),
            }

    objective_vector: dict[str, float] = {}

    def weighted_summary_metric(metric_name: str) -> float:
        return _weighted_average(
            [
                (slice_summaries[slice_cfg.name].get(metric_name, 0.0), slice_cfg.weight)
                for slice_cfg in slices
            ]
        )

    objective_vector["global.slot_gain"] = weighted_summary_metric("avg_slot_recall_gain")
    objective_vector["global.keyword_gain"] = weighted_summary_metric("avg_keyword_recall_gain")
    objective_vector["global.hierarchy_win_rate"] = weighted_summary_metric("hierarchy_win_rate")
    objective_vector["global.token_delta"] = weighted_summary_metric("avg_retrieved_token_delta")
    objective_vector["global.slot_per_token_gain"] = weighted_summary_metric("avg_slot_recall_per_token_gain")
    objective_vector["global.flat_win_penalty"] = -weighted_summary_metric("flat_win_rate")
    objective_vector["robust.worst_slot_gain"] = min(
        (slice_summaries[slice_cfg.name]["avg_slot_recall_gain"] for slice_cfg in slices),
        default=0.0,
    )
    objective_vector["robust.worst_keyword_gain"] = min(
        (slice_summaries[slice_cfg.name]["avg_keyword_recall_gain"] for slice_cfg in slices),
        default=0.0,
    )

    for family_objective in family_objectives:
        alias = _metric_alias(family_objective.metric)
        weighted_family_metric = _weighted_average(
            [
                (
                    family_slice_metrics.get(slice_cfg.name, {})
                    .get(family_objective.family, {})
                    .get(alias, 0.0),
                    slice_cfg.weight,
                )
                for slice_cfg in slices
            ]
        )
        maximize_value = weighted_family_metric if family_objective.direction == "max" else -weighted_family_metric
        objective_vector[_objective_name_for_family(family_objective)] = maximize_value

    objective_seed_statistics = _weighted_seed_objective_stats(
        slices=slices,
        slice_seed_stats=slice_seed_statistics,
    )
    _log(
        (
            f"{run_prefix}: candidate={candidate_id} completed in {(time.monotonic() - candidate_started)/60.0:.1f}m; "
            f"slot_gain={objective_vector.get('global.slot_gain', 0.0):.4f}, "
            f"token_delta={objective_vector.get('global.token_delta', 0.0):.2f}."
        ),
        enabled=log_progress,
    )

    return CandidateResult(
        candidate_id=candidate_id,
        overrides=overrides,
        objective_vector=objective_vector,
        utility_score=0.0,  # assigned after objective normalization across all candidates
        slice_summaries=slice_summaries,
        family_slice_metrics=family_slice_metrics,
        slice_seed_statistics=slice_seed_statistics,
        objective_seed_statistics=objective_seed_statistics,
    )


def _dominates(left: CandidateResult, right: CandidateResult, *, epsilon: float) -> bool:
    keys = sorted(set(left.objective_vector.keys()) | set(right.objective_vector.keys()))
    left_values = [left.objective_vector.get(key, 0.0) for key in keys]
    right_values = [right.objective_vector.get(key, 0.0) for key in keys]
    not_worse = all(lv >= (rv - epsilon) for lv, rv in zip(left_values, right_values))
    strictly_better = any(lv > (rv + epsilon) for lv, rv in zip(left_values, right_values))
    return not_worse and strictly_better


def _frontier(results: list[CandidateResult], *, epsilon: float) -> list[CandidateResult]:
    selected: list[CandidateResult] = []
    for candidate in results:
        dominated = False
        for other in results:
            if other.candidate_id == candidate.candidate_id:
                continue
            if _dominates(other, candidate, epsilon=epsilon):
                dominated = True
                break
        if not dominated:
            selected.append(candidate)
    return sorted(selected, key=lambda item: item.utility_score, reverse=True)


def _utility_weights(objective_keys: list[str], family_objectives: list[FamilyObjective]) -> dict[str, float]:
    base_weights = {
        "global.slot_gain": 0.24,
        "global.keyword_gain": 0.16,
        "global.hierarchy_win_rate": 0.14,
        "global.token_delta": 0.10,
        "global.slot_per_token_gain": 0.08,
        "global.flat_win_penalty": 0.08,
        "robust.worst_slot_gain": 0.12,
        "robust.worst_keyword_gain": 0.08,
    }
    family_keys = [_objective_name_for_family(item) for item in family_objectives]
    family_keys = [key for key in family_keys if key in objective_keys]
    if family_keys:
        scale = 0.7
        weights = {key: value * scale for key, value in base_weights.items() if key in objective_keys}
        per_family = 0.3 / len(family_keys)
        for key in family_keys:
            weights[key] = per_family
    else:
        weights = {key: value for key, value in base_weights.items() if key in objective_keys}
    total = sum(weights.values())
    if total <= 0:
        return {key: 1.0 / max(len(objective_keys), 1) for key in objective_keys}
    return {key: value / total for key, value in weights.items()}


def _assign_utility_scores(
    candidates: list[CandidateResult],
    *,
    family_objectives: list[FamilyObjective],
) -> list[CandidateResult]:
    if not candidates:
        return []
    objective_keys = sorted({key for candidate in candidates for key in candidate.objective_vector.keys()})
    weights = _utility_weights(objective_keys, family_objectives)
    by_key: dict[str, list[float]] = {key: [candidate.objective_vector.get(key, 0.0) for candidate in candidates] for key in objective_keys}
    mins = {key: min(values) for key, values in by_key.items()}
    maxs = {key: max(values) for key, values in by_key.items()}

    rescored: list[CandidateResult] = []
    for candidate in candidates:
        utility = 0.0
        for key in objective_keys:
            raw_value = candidate.objective_vector.get(key, 0.0)
            lo, hi = mins[key], maxs[key]
            if hi <= lo:
                normalized = 0.5
            else:
                normalized = (raw_value - lo) / (hi - lo)
            utility += weights.get(key, 0.0) * normalized
        rescored.append(
            CandidateResult(
                candidate_id=candidate.candidate_id,
                overrides=candidate.overrides,
                objective_vector=candidate.objective_vector,
                utility_score=utility,
                slice_summaries=candidate.slice_summaries,
                family_slice_metrics=candidate.family_slice_metrics,
                slice_seed_statistics=candidate.slice_seed_statistics,
                objective_seed_statistics=candidate.objective_seed_statistics,
            )
        )
    return sorted(rescored, key=lambda item: item.utility_score, reverse=True)


def _run_single_sweep(
    *,
    max_candidates: int,
    sample_method: str,
    random_seed: int,
    dimensions: list[SweepDimension],
    base_policy: dict[str, Any],
    slices: list[EvalSlice],
    families: tuple[str, ...] | None,
    family_objectives: list[FamilyObjective],
    use_quick_scenarios: bool,
    scenario_limit: int | None,
    pareto_epsilon: float,
    candidate_workers: int,
    resume_candidates: dict[str, CandidateResult] | None,
    on_candidate_complete: Callable[[CandidateResult], None] | None,
    log_progress: bool,
    log_every_candidates: int,
    log_every_scenarios: int,
) -> SweepRunResult:
    """Run one optimizer sweep for one random seed
    Samples policy overrides evaluates candidates and extracts local frontier"""
    rng = random.Random(random_seed)
    sampled_overrides = _sample_overrides(dimensions, max_candidates=max_candidates, sample_method=sample_method, rng=rng)
    all_candidates: list[tuple[str, dict[str, float]]] = [("baseline", {})]
    all_candidates.extend((f"candidate_{index + 1:04d}", overrides) for index, overrides in enumerate(sampled_overrides))
    total_candidates = len(all_candidates)
    run_started = time.monotonic()
    _log(
        (
            f"run seed={random_seed}: evaluating {total_candidates} candidates "
            f"({len(sampled_overrides)} sampled + baseline)."
        ),
        enabled=log_progress,
    )

    valid_candidate_ids = {candidate_id for candidate_id, _ in all_candidates}
    restored = {cid: result for cid, result in (resume_candidates or {}).items() if cid in valid_candidate_ids}
    evaluated_by_id: dict[str, CandidateResult] = dict(restored)
    pending_candidates = [(cid, ov) for cid, ov in all_candidates if cid not in evaluated_by_id]
    if restored:
        _log(
            (
                f"run seed={random_seed}: restored {len(restored)} candidates from checkpoint; "
                f"{len(pending_candidates)} remaining."
            ),
            enabled=log_progress,
        )

    evaluated: list[CandidateResult] = list(evaluated_by_id.values())
    interval = max(1, log_every_candidates)
    workers = max(1, int(candidate_workers))

    def _run_candidates_serial() -> None:
        completed_count = len(evaluated_by_id)
        for index, (candidate_id, overrides) in enumerate(pending_candidates, start=1):
            candidate_started = time.monotonic()
            result = _evaluate_candidate(
                candidate_id=candidate_id,
                overrides=overrides,
                base_policy=base_policy,
                slices=slices,
                families=families,
                family_objectives=family_objectives,
                use_quick_scenarios=use_quick_scenarios,
                scenario_limit=scenario_limit,
                run_seed=random_seed,
                log_progress=log_progress,
                log_every_scenarios=log_every_scenarios,
            )
            evaluated_by_id[result.candidate_id] = result
            evaluated.append(result)
            completed_count += 1
            if on_candidate_complete is not None:
                on_candidate_complete(result)
            if log_progress and (
                completed_count == 1
                or completed_count == total_candidates
                or completed_count % interval == 0
            ):
                elapsed = time.monotonic() - run_started
                candidate_elapsed = time.monotonic() - candidate_started
                rate = completed_count / elapsed if elapsed > 0 else 0.0
                remaining = total_candidates - completed_count
                eta_seconds = (remaining / rate) if rate > 0 else 0.0
                _log(
                    (
                        f"run seed={random_seed}: candidate {completed_count}/{total_candidates} ({candidate_id}) "
                        f"done in {candidate_elapsed:.1f}s; elapsed={elapsed/60.0:.1f}m; "
                        f"ETA={eta_seconds/60.0:.1f}m."
                    ),
                    enabled=True,
                )

    if not pending_candidates:
        _log(
            f"run seed={random_seed}: all candidates already completed in checkpoint.",
            enabled=log_progress,
        )
    elif workers == 1:
        # serial mode for simple local execution
        _run_candidates_serial()
    else:
        # process pool mode for faster candidate throughput
        _log(
            f"run seed={random_seed}: parallel candidate evaluation enabled with workers={workers}.",
            enabled=log_progress,
        )
        futures = {}
        try:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                for index, (candidate_id, overrides) in enumerate(pending_candidates, start=1):
                    started = time.monotonic()
                    future = executor.submit(
                        _evaluate_candidate,
                        candidate_id=candidate_id,
                        overrides=overrides,
                        base_policy=base_policy,
                        slices=slices,
                        families=families,
                        family_objectives=family_objectives,
                        use_quick_scenarios=use_quick_scenarios,
                        scenario_limit=scenario_limit,
                        run_seed=random_seed,
                        log_progress=False,
                        log_every_scenarios=0,
                    )
                    futures[future] = (index, candidate_id, started)

                for completed_count, future in enumerate(as_completed(futures), start=1):
                    index, candidate_id, candidate_started = futures[future]
                    result = future.result()
                    evaluated_by_id[result.candidate_id] = result
                    evaluated.append(result)
                    if on_candidate_complete is not None:
                        on_candidate_complete(result)
                    if log_progress and (
                        (completed_count + len(restored)) == 1
                        or (completed_count + len(restored)) == total_candidates
                        or completed_count % interval == 0
                    ):
                        elapsed = time.monotonic() - run_started
                        candidate_elapsed = time.monotonic() - candidate_started
                        absolute_completed = completed_count + len(restored)
                        rate = absolute_completed / elapsed if elapsed > 0 else 0.0
                        remaining = total_candidates - absolute_completed
                        eta_seconds = (remaining / rate) if rate > 0 else 0.0
                        _log(
                            (
                                f"run seed={random_seed}: candidate {absolute_completed}/{total_candidates} "
                                f"(submitted as #{index}, id={candidate_id}) done in {candidate_elapsed:.1f}s; "
                                f"elapsed={elapsed/60.0:.1f}m; ETA={eta_seconds/60.0:.1f}m."
                            ),
                            enabled=True,
                        )
        except (PermissionError, OSError) as exc:
            _log(
                (
                    f"run seed={random_seed}: process workers unavailable ({exc}); "
                    "falling back to serial candidate evaluation."
                ),
                enabled=True,
            )
            futures.clear()
            _run_candidates_serial()

    evaluated = _assign_utility_scores(evaluated, family_objectives=family_objectives)
    frontier_rows = _frontier(evaluated, epsilon=pareto_epsilon)
    _log(
        (
            f"run seed={random_seed}: completed with {len(frontier_rows)} frontier candidates "
            f"in {(time.monotonic() - run_started)/60.0:.1f}m."
        ),
        enabled=log_progress,
    )
    return SweepRunResult(random_seed=random_seed, candidates=evaluated, frontier=frontier_rows)


def _normalized_metric_distance(
    *,
    left: dict[str, float],
    right: dict[str, float],
    mins: dict[str, float],
    maxs: dict[str, float],
    keys: tuple[str, ...],
) -> float:
    if not keys:
        return 0.0
    squared = 0.0
    for key in keys:
        lo = mins.get(key, 0.0)
        hi = maxs.get(key, lo)
        span = hi - lo
        lv = left.get(key, 0.0)
        rv = right.get(key, 0.0)
        if span > 0:
            diff = (lv - rv) / span
        else:
            diff = 0.0
        squared += diff * diff
    return math.sqrt(squared / len(keys))


def _candidate_projection(candidate: CandidateResult, keys: tuple[str, ...]) -> dict[str, float]:
    return {key: float(candidate.objective_vector.get(key, 0.0)) for key in keys}


def _frontier_stability_report(
    runs: list[SweepRunResult],
    *,
    mode_match_threshold: float,
) -> tuple[dict[str, Any], dict[tuple[int, str], str]]:
    if not runs:
        return {
            "mode_count": 0,
            "mode_match_threshold": mode_match_threshold,
            "runs": [],
            "modes": [],
            "pairwise_mode_jaccard": [],
            "average_pairwise_mode_jaccard": 0.0,
        }, {}

    frontier_points: list[tuple[int, SweepRunResult, CandidateResult]] = []
    for run_index, run in enumerate(runs):
        for candidate in run.frontier:
            frontier_points.append((run_index, run, candidate))

    mins: dict[str, float] = {}
    maxs: dict[str, float] = {}
    for key in STABILITY_FEATURE_KEYS:
        values = [candidate.objective_vector.get(key, 0.0) for _, _, candidate in frontier_points]
        mins[key] = min(values) if values else 0.0
        maxs[key] = max(values) if values else 0.0

    modes: list[dict[str, Any]] = []
    assignment_lookup: dict[tuple[int, str], str] = {}
    for run_index, run, candidate in frontier_points:
        projection = _candidate_projection(candidate, STABILITY_FEATURE_KEYS)
        best_mode_index: int | None = None
        best_distance = float("inf")
        for mode_index, mode in enumerate(modes):
            distance = _normalized_metric_distance(
                left=projection,
                right=mode["centroid"],
                mins=mins,
                maxs=maxs,
                keys=STABILITY_FEATURE_KEYS,
            )
            if distance < best_distance:
                best_distance = distance
                best_mode_index = mode_index

        if best_mode_index is None or best_distance > mode_match_threshold:
            mode_id = f"mode_{len(modes) + 1:02d}"
            new_mode = {
                "mode_id": mode_id,
                "centroid": projection,
                "members": [],
            }
            modes.append(new_mode)
            best_mode_index = len(modes) - 1

        mode = modes[best_mode_index]
        mode["members"].append(
            {
                "run_index": run_index,
                "random_seed": run.random_seed,
                "candidate_id": candidate.candidate_id,
                "utility_score": candidate.utility_score,
                "objective_vector": candidate.objective_vector,
            }
        )
        member_count = len(mode["members"])
        for key in STABILITY_FEATURE_KEYS:
            old = mode["centroid"].get(key, 0.0)
            new = projection.get(key, 0.0)
            mode["centroid"][key] = old + (new - old) / member_count
        assignment_lookup[(run_index, candidate.candidate_id)] = mode["mode_id"]

    run_rows: list[dict[str, Any]] = []
    run_mode_sets: list[set[str]] = []
    for run_index, run in enumerate(runs):
        assignments = [
            {
                "candidate_id": candidate.candidate_id,
                "mode_id": assignment_lookup.get((run_index, candidate.candidate_id), "unassigned"),
                "utility_score": candidate.utility_score,
            }
            for candidate in run.frontier
        ]
        mode_set = {row["mode_id"] for row in assignments if row["mode_id"] != "unassigned"}
        run_mode_sets.append(mode_set)
        run_rows.append(
            {
                "run_index": run_index,
                "random_seed": run.random_seed,
                "frontier_size": len(run.frontier),
                "frontier_mode_ids": sorted(mode_set),
                "frontier_candidates": assignments,
            }
        )

    mode_rows: list[dict[str, Any]] = []
    for mode in modes:
        members = mode["members"]
        run_ids = sorted({int(member["run_index"]) for member in members})
        random_seeds = sorted({int(member["random_seed"]) for member in members})
        representative = max(members, key=lambda member: member["utility_score"])
        metric_movement: dict[str, dict[str, float]] = {}
        for key in STABILITY_FEATURE_KEYS:
            values = [float(member["objective_vector"].get(key, 0.0)) for member in members]
            metric_movement[key] = {
                "mean": statistics.fmean(values) if values else 0.0,
                "stddev": _sample_stddev(values),
                "min": min(values) if values else 0.0,
                "max": max(values) if values else 0.0,
                "range": (max(values) - min(values)) if values else 0.0,
            }
        mode_rows.append(
            {
                "mode_id": mode["mode_id"],
                "appearance_count": len(run_ids),
                "appearance_rate": len(run_ids) / max(len(runs), 1),
                "candidate_occurrence_count": len(members),
                "run_indices": run_ids,
                "random_seeds": random_seeds,
                "centroid_objectives": mode["centroid"],
                "representative": representative,
                "metric_movement": metric_movement,
            }
        )
    mode_rows.sort(key=lambda item: (item["appearance_count"], item["candidate_occurrence_count"]), reverse=True)

    pairwise: list[dict[str, Any]] = []
    for left_index in range(len(runs)):
        for right_index in range(left_index + 1, len(runs)):
            left_modes = run_mode_sets[left_index]
            right_modes = run_mode_sets[right_index]
            union = left_modes | right_modes
            score = (len(left_modes & right_modes) / len(union)) if union else 1.0
            pairwise.append(
                {
                    "left_run_index": left_index,
                    "right_run_index": right_index,
                    "left_random_seed": runs[left_index].random_seed,
                    "right_random_seed": runs[right_index].random_seed,
                    "mode_jaccard": score,
                }
            )
    avg_jaccard = statistics.fmean([row["mode_jaccard"] for row in pairwise]) if pairwise else 1.0
    report = {
        "mode_count": len(mode_rows),
        "mode_match_threshold": mode_match_threshold,
        "runs": run_rows,
        "modes": mode_rows,
        "pairwise_mode_jaccard": pairwise,
        "average_pairwise_mode_jaccard": avg_jaccard,
    }
    return report, assignment_lookup


def _candidate_json_payload(
    candidate: CandidateResult,
    *,
    is_frontier: bool,
    mode_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_id": candidate.candidate_id,
        "is_frontier": is_frontier,
        "utility_score": candidate.utility_score,
        "overrides": candidate.overrides,
        "objective_vector": candidate.objective_vector,
        "objective_seed_statistics": candidate.objective_seed_statistics,
        "slice_summaries": candidate.slice_summaries,
        "slice_seed_statistics": candidate.slice_seed_statistics,
        "family_slice_metrics": candidate.family_slice_metrics,
    }
    if mode_id:
        payload["stability_mode_id"] = mode_id
    return payload


def _candidate_checkpoint_payload(candidate: CandidateResult) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "overrides": candidate.overrides,
        "objective_vector": candidate.objective_vector,
        "utility_score": candidate.utility_score,
        "slice_summaries": candidate.slice_summaries,
        "family_slice_metrics": candidate.family_slice_metrics,
        "slice_seed_statistics": candidate.slice_seed_statistics,
        "objective_seed_statistics": candidate.objective_seed_statistics,
    }


def _candidate_from_checkpoint(payload: dict[str, Any]) -> CandidateResult:
    return CandidateResult(
        candidate_id=str(payload.get("candidate_id", "")),
        overrides=dict(payload.get("overrides", {})),
        objective_vector=dict(payload.get("objective_vector", {})),
        utility_score=float(payload.get("utility_score", 0.0)),
        slice_summaries=dict(payload.get("slice_summaries", {})),
        family_slice_metrics=dict(payload.get("family_slice_metrics", {})),
        slice_seed_statistics=dict(payload.get("slice_seed_statistics", {})),
        objective_seed_statistics=dict(payload.get("objective_seed_statistics", {})),
    )


def _stable_config_signature(config: dict[str, Any]) -> str:
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _load_checkpoint(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class FrontierCheckpointStore:
    path: Path | None
    config_signature: str
    config_payload: dict[str, Any]
    state: dict[str, Any] | None
    runs_by_seed: dict[int, dict[str, Any]]

    @classmethod
    def create(
        cls,
        *,
        path: Path | None,
        config_payload: dict[str, Any],
        log_progress: bool,
    ) -> "FrontierCheckpointStore":
        config_signature = _stable_config_signature(config_payload)
        if path is None:
            return cls(
                path=None,
                config_signature=config_signature,
                config_payload=config_payload,
                state=None,
                runs_by_seed={},
            )

        runs_by_seed: dict[int, dict[str, Any]] = {}
        if path.exists():
            state = _load_checkpoint(path)
            existing_signature = str(state.get("config_signature", ""))
            if existing_signature != config_signature:
                raise ValueError(
                    "Checkpoint config mismatch. Remove checkpoint file or use a different --checkpoint-path."
                )
            for run_payload in state.get("runs", []):
                seed_value = int(run_payload.get("random_seed"))
                runs_by_seed[seed_value] = run_payload
            _log(
                f"loaded checkpoint from {path} with {len(runs_by_seed)} run entries.",
                enabled=log_progress,
            )
            return cls(
                path=path,
                config_signature=config_signature,
                config_payload=config_payload,
                state=state,
                runs_by_seed=runs_by_seed,
            )

        state = {
            "format_version": CHECKPOINT_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config_signature": config_signature,
            "config": config_payload,
            "runs": [],
        }
        _write_checkpoint(path, state)
        _log(f"initialized checkpoint at {path}.", enabled=log_progress)
        return cls(
            path=path,
            config_signature=config_signature,
            config_payload=config_payload,
            state=state,
            runs_by_seed=runs_by_seed,
        )

    def _persist(self) -> None:
        if self.path is None or self.state is None:
            return
        _write_checkpoint(self.path, self.state)

    def _ensure_run_state(self, *, run_index: int, random_seed: int) -> dict[str, Any] | None:
        if self.state is None:
            return None
        run_state = self.runs_by_seed.get(random_seed)
        if run_state is not None:
            return run_state
        run_state = {
            "run_index": run_index,
            "random_seed": random_seed,
            "status": "in_progress",
            "completed_candidates": {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.runs_by_seed[random_seed] = run_state
        self.state["runs"].append(run_state)
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._persist()
        return run_state

    def restored_candidates(self, *, run_index: int, random_seed: int) -> dict[str, CandidateResult]:
        run_state = self._ensure_run_state(run_index=run_index, random_seed=random_seed)
        if run_state is None:
            return {}
        restored_candidates: dict[str, CandidateResult] = {}
        for candidate_id, candidate_payload in run_state.get("completed_candidates", {}).items():
            restored = _candidate_from_checkpoint(candidate_payload)
            if restored.candidate_id != candidate_id:
                restored = CandidateResult(
                    candidate_id=candidate_id,
                    overrides=restored.overrides,
                    objective_vector=restored.objective_vector,
                    utility_score=restored.utility_score,
                    slice_summaries=restored.slice_summaries,
                    family_slice_metrics=restored.family_slice_metrics,
                    slice_seed_statistics=restored.slice_seed_statistics,
                    objective_seed_statistics=restored.objective_seed_statistics,
                )
            restored_candidates[candidate_id] = restored
        return restored_candidates

    def record_candidate(self, *, random_seed: int, result: CandidateResult) -> None:
        if self.state is None:
            return
        run_state = self.runs_by_seed.get(random_seed)
        if run_state is None:
            return
        completed = run_state.setdefault("completed_candidates", {})
        completed[result.candidate_id] = _candidate_checkpoint_payload(result)
        run_state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.state["updated_at"] = run_state["updated_at"]
        self._persist()

    def mark_run_completed(self, *, random_seed: int, frontier_candidate_ids: list[str]) -> None:
        if self.state is None:
            return
        run_state = self.runs_by_seed.get(random_seed)
        if run_state is None:
            return
        run_state["status"] = "completed"
        run_state["frontier_candidate_ids"] = frontier_candidate_ids
        run_state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.state["updated_at"] = run_state["updated_at"]
        self._persist()


def run_frontier_sweep(
    *,
    seeds: tuple[int, ...],
    families: tuple[str, ...] | None,
    dimensions: list[SweepDimension],
    max_candidates: int,
    sample_method: str,
    random_seed: int,
    optimization_random_seeds: tuple[int, ...] | None,
    slices: list[EvalSlice],
    family_objectives: list[FamilyObjective],
    use_quick_scenarios: bool,
    scenario_limit: int | None,
    pareto_epsilon: float,
    mode_match_threshold: float,
    candidate_workers: int,
    checkpoint_path: Path | None,
    log_progress: bool,
    log_every_candidates: int,
    log_every_scenarios: int,
) -> dict[str, Any]:
    """Run full frontier workflow
    Repeats sweeps for stability analysis then builds export payload"""
    base_policy = load_query_routing_policy(Path(os.getenv("PROJECT_QUERY_ROUTING_POLICY_PATH", str(QUERY_ROUTING_POLICY_PATH))))
    run_seeds = list(optimization_random_seeds or (random_seed,))
    if not run_seeds:
        run_seeds = [random_seed]
    deduped_run_seeds = tuple(dict.fromkeys(run_seeds))
    scenarios_per_candidate = sum(
        len(
            _scenarios_for_slice(
                slice_cfg,
                families,
                use_quick_scenarios=use_quick_scenarios,
                scenario_limit=scenario_limit,
            )
        )
        for slice_cfg in slices
    )
    projected_total_candidates = (max_candidates + 1) * len(deduped_run_seeds)
    projected_total_scenario_evals = projected_total_candidates * scenarios_per_candidate
    checkpoint_config = {
        "seeds": list(seeds),
        "families": list(families) if families else None,
        "dimensions": [
            {
                "key": item.key,
                "min": item.min_value,
                "max": item.max_value,
                "type": item.value_type,
            }
            for item in dimensions
        ],
        "max_candidates": max_candidates,
        "sample_method": sample_method,
        "optimization_random_seeds": list(deduped_run_seeds),
        "slices": [
            {
                "name": item.name,
                "weight": item.weight,
                "seeds": list(item.seeds),
                "perturbation_styles": list(item.perturbation_styles),
            }
            for item in slices
        ],
        "family_objectives": [
            {"family": item.family, "metric": item.metric, "direction": item.direction}
            for item in family_objectives
        ],
        "quick_scenarios": use_quick_scenarios,
        "scenario_limit": scenario_limit,
        "pareto_epsilon": pareto_epsilon,
    }
    checkpoint_store = FrontierCheckpointStore.create(
        path=checkpoint_path,
        config_payload=checkpoint_config,
        log_progress=log_progress,
    )

    _log(
        (
            f"starting frontier sweep: runs={len(deduped_run_seeds)}, sample_method={sample_method}, "
            f"max_candidates={max_candidates}, slices={','.join(slice_cfg.name for slice_cfg in slices)}."
        ),
        enabled=log_progress,
    )
    _log(
        (
            f"projected workload: {projected_total_candidates} candidates total, "
            f"~{projected_total_scenario_evals} scenario evaluations."
        ),
        enabled=log_progress,
    )

    sweep_started = time.monotonic()
    runs: list[SweepRunResult] = []
    # iterate optimizer seeds for stability analysis
    for run_index, seed_value in enumerate(deduped_run_seeds, start=1):
        restored_candidates = checkpoint_store.restored_candidates(
            run_index=run_index - 1,
            random_seed=seed_value,
        )

        def _on_candidate_complete(result: CandidateResult) -> None:
            checkpoint_store.record_candidate(random_seed=seed_value, result=result)

        _log(
            f"starting optimization run {run_index}/{len(deduped_run_seeds)} with random_seed={seed_value}.",
            enabled=log_progress,
        )
        run_result = _run_single_sweep(
            max_candidates=max_candidates,
            sample_method=sample_method,
            random_seed=seed_value,
            dimensions=dimensions,
            base_policy=base_policy,
            slices=slices,
            families=families,
            family_objectives=family_objectives,
            use_quick_scenarios=use_quick_scenarios,
            scenario_limit=scenario_limit,
            pareto_epsilon=pareto_epsilon,
            candidate_workers=candidate_workers,
            resume_candidates=restored_candidates,
            on_candidate_complete=_on_candidate_complete if checkpoint_store.state is not None else None,
            log_progress=log_progress,
            log_every_candidates=log_every_candidates,
            log_every_scenarios=log_every_scenarios,
        )
        runs.append(run_result)
        checkpoint_store.mark_run_completed(
            random_seed=seed_value,
            frontier_candidate_ids=[item.candidate_id for item in run_result.frontier],
        )
        _log(
            f"finished optimization run {run_index}/{len(deduped_run_seeds)} with frontier_size={len(run_result.frontier)}.",
            enabled=log_progress,
        )

    stability_report, assignment_lookup = _frontier_stability_report(runs, mode_match_threshold=mode_match_threshold)
    payload = build_frontier_report_payload(
        runs=runs,
        slices=slices,
        dimensions=dimensions,
        families=families,
        family_objectives=family_objectives,
        sample_method=sample_method,
        max_candidates=max_candidates,
        deduped_run_seeds=deduped_run_seeds,
        use_quick_scenarios=use_quick_scenarios,
        scenario_limit=scenario_limit,
        pareto_epsilon=pareto_epsilon,
        mode_match_threshold=mode_match_threshold,
        stability_report=stability_report,
        assignment_lookup=assignment_lookup,
        candidate_payload_builder=_candidate_json_payload,
    )
    _log(
        f"frontier sweep complete in {(time.monotonic() - sweep_started)/60.0:.1f}m.",
        enabled=log_progress,
    )
    return payload


def main() -> None:
    """CLI entrypoint
    Parses sweep args executes run and writes report artifacts"""
    parser = argparse.ArgumentParser(description="Run a large frontier sweep with multi-slice objectives.")
    parser.add_argument(
        "--seed",
        dest="seeds",
        action="append",
        type=int,
        help="Scenario seed(s) for canonical slice. Repeat for multiple seeds.",
    )
    parser.add_argument(
        "--family",
        dest="families",
        action="append",
        help="Optional family filter. Repeat for multiple families.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=180,
        help="Number of sampled policy candidates (baseline is always included). Suggested: 150-300.",
    )
    parser.add_argument(
        "--sample-method",
        choices=("lhs", "random"),
        default="lhs",
        help="Sampling method for policy space.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=7,
        help="RNG seed used for candidate sampling.",
    )
    parser.add_argument(
        "--optimization-seed",
        dest="optimization_seeds",
        action="append",
        type=int,
        default=None,
        help=(
            "Optimization random seed(s) for repeated frontier runs. "
            "If provided, these override --random-seed and --optimization-runs."
        ),
    )
    parser.add_argument(
        "--optimization-runs",
        type=int,
        default=1,
        help=(
            "Number of optimization runs with different random seeds. "
            "When >1 and --optimization-seed is not provided, seeds are "
            "generated as random_seed + run_index."
        ),
    )
    parser.add_argument(
        "--sweep-space",
        type=Path,
        default=None,
        help="Optional JSON sweep-space definition. Format: dotted-key -> {min,max,type}.",
    )
    parser.add_argument(
        "--family-objective",
        action="append",
        default=None,
        help="Family-level objective as family:metric[:max|min]. Repeat for multiple objectives.",
    )
    parser.add_argument(
        "--no-unseen-slice",
        action="store_true",
        help="Disable unseen-seed slice in objective.",
    )
    parser.add_argument(
        "--unseen-offset",
        dest="unseen_offsets",
        action="append",
        type=int,
        default=None,
        help="Offset(s) added to canonical seeds for unseen slice (default: 100). Repeat for multiple offsets.",
    )
    parser.add_argument(
        "--no-perturbation-slice",
        action="store_true",
        help="Disable perturbation slice in objective.",
    )
    parser.add_argument(
        "--objective-perturbation-style",
        dest="objective_perturbation_styles",
        action="append",
        choices=list(QUERY_PERTURBATION_STYLES),
        default=None,
        help=(
            "Perturbation styles to include in the hard slice "
            "(default: concise, indirect, typo_noise)."
        ),
    )
    parser.add_argument(
        "--candidate-workers",
        type=int,
        default=1,
        help=(
            "Number of parallel worker processes for candidate evaluation. "
            "Use 1 for serial execution."
        ),
    )
    parser.add_argument(
        "--slice-weight-canonical",
        type=float,
        default=0.50,
        help="Canonical slice weight before normalization.",
    )
    parser.add_argument(
        "--slice-weight-unseen",
        type=float,
        default=0.25,
        help="Unseen-seed slice weight before normalization.",
    )
    parser.add_argument(
        "--slice-weight-perturb",
        type=float,
        default=0.25,
        help="Perturbation slice weight before normalization.",
    )
    parser.add_argument(
        "--pareto-epsilon",
        type=float,
        default=1e-4,
        help="Soft dominance epsilon for Pareto comparison.",
    )
    parser.add_argument(
        "--mode-match-threshold",
        type=float,
        default=0.18,
        help="Normalized objective-distance threshold used to match frontier modes across optimization runs.",
    )
    parser.add_argument(
        "--quick-scenarios",
        action="store_true",
        help="Use the quick scenario subset instead of the full scenario suite for each slice.",
    )
    parser.add_argument(
        "--scenario-limit",
        type=int,
        default=None,
        help="Optional hard cap on scenarios per slice after filtering/perturbation.",
    )
    parser.add_argument(
        "--log-every-candidates",
        type=int,
        default=5,
        help="Emit progress logs every N evaluated candidates within each optimization run.",
    )
    parser.add_argument(
        "--log-every-scenarios",
        type=int,
        default=0,
        help=(
            "Emit within-slice progress every N scenarios for each candidate. "
            "Use 0 to disable scenario-level logs."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable frontier progress logging.",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        default=None,
        help=(
            "Optional checkpoint JSON path. If present, candidate evaluations are checkpointed "
            "and an existing file is resumed automatically."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPORTS_DIR,
        help="Directory to write frontier artifacts.",
    )
    parser.add_argument(
        "--stem",
        type=str,
        default=None,
        help="Optional stem for output files.",
    )
    args = parser.parse_args()

    seeds = tuple(args.seeds) if args.seeds else DEFAULT_SCENARIO_SEEDS
    families = tuple(args.families) if args.families else None
    dimensions = _load_sweep_space(args.sweep_space)
    family_objective_strings = tuple(args.family_objective) if args.family_objective else DEFAULT_FAMILY_OBJECTIVES
    family_objectives = [_parse_family_objective(item) for item in family_objective_strings]
    if families:
        family_filter = set(families)
        family_objectives = [item for item in family_objectives if item.family in family_filter]

    unseen_offsets = tuple(args.unseen_offsets) if args.unseen_offsets else (100,)
    perturbation_styles = (
        tuple(args.objective_perturbation_styles)
        if args.objective_perturbation_styles
        else DEFAULT_HARD_PERTURBATION_STYLES
    )
    slices = _build_slices(
        seeds=seeds,
        include_unseen_slice=not args.no_unseen_slice,
        unseen_offsets=unseen_offsets,
        include_perturbation_slice=not args.no_perturbation_slice,
        perturbation_styles=perturbation_styles,
        canonical_weight=max(0.0, args.slice_weight_canonical),
        unseen_weight=max(0.0, args.slice_weight_unseen),
        perturbation_weight=max(0.0, args.slice_weight_perturb),
    )
    if args.optimization_seeds:
        optimization_random_seeds = tuple(args.optimization_seeds)
    else:
        run_count = max(1, int(args.optimization_runs))
        optimization_random_seeds = tuple(args.random_seed + index for index in range(run_count))

    payload = run_frontier_sweep(
        seeds=seeds,
        families=families,
        dimensions=dimensions,
        max_candidates=max(1, args.max_candidates),
        sample_method=args.sample_method,
        random_seed=args.random_seed,
        optimization_random_seeds=optimization_random_seeds,
        slices=slices,
        family_objectives=family_objectives,
        use_quick_scenarios=args.quick_scenarios,
        scenario_limit=(max(1, args.scenario_limit) if args.scenario_limit is not None else None),
        pareto_epsilon=max(0.0, args.pareto_epsilon),
        mode_match_threshold=max(0.0, args.mode_match_threshold),
        candidate_workers=max(1, int(args.candidate_workers)),
        checkpoint_path=args.checkpoint_path,
        log_progress=not args.quiet,
        log_every_candidates=max(1, int(args.log_every_candidates)),
        log_every_scenarios=max(0, int(args.log_every_scenarios)),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.stem or f"frontier_sweep_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    json_path = args.output_dir / f"{stem}.json"
    md_path = args.output_dir / f"{stem}.md"
    if args.checkpoint_path is not None and args.checkpoint_path.resolve() == json_path.resolve():
        raise ValueError("--checkpoint-path must be different from the final JSON report path.")
    json_payload = dict(payload)
    markdown = json_payload.pop("markdown")
    json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
