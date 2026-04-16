from __future__ import annotations

"""Quality gate checks for eval outputs
Validates thresholds and emits pass fail status"""

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from packages.evals.runner import run_scenario_instance
from packages.evals.scenarios import (
    DEFAULT_SCENARIO_SEEDS,
    QUERY_PERTURBATION_STYLES,
    all_scenarios,
    scenario_with_perturbation,
)
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings
from packages.schemas.models import EvalRunResult


@dataclass(frozen=True)
class GateRow:
    family: str
    variant: str
    seed: int
    baseline_keyword: float
    baseline_slot: float
    hierarchy_keyword: float
    hierarchy_slot: float
    keyword_gain: float
    slot_gain: float
    token_delta: float
    winner: str
    scenario_name: str
    routing_strategy: str | None
    fired_rules: tuple[str, ...]


def _metric_map(result: EvalRunResult, *, baseline: bool) -> dict[str, float]:
    metrics = result.baseline_metrics if baseline else result.hierarchy_metrics
    return {metric.name: metric.value for metric in metrics}


def _variant_name(scenario_name: str) -> str:
    marker = "__qp_"
    if marker not in scenario_name:
        return "canonical"
    return scenario_name.split(marker, 1)[1]


def _winner(baseline: dict[str, float], hierarchy: dict[str, float]) -> str:
    if hierarchy["slot_recall"] > baseline["slot_recall"]:
        return "hierarchy"
    if hierarchy["slot_recall"] < baseline["slot_recall"]:
        return "flat"
    if hierarchy["keyword_recall"] > baseline["keyword_recall"]:
        return "hierarchy"
    if hierarchy["keyword_recall"] < baseline["keyword_recall"]:
        return "flat"
    return "tie"


def _routing_attribution(result: EvalRunResult) -> tuple[str | None, tuple[str, ...]]:
    for metric in result.hierarchy_metrics:
        if metric.name == "routing_attribution":
            strategy = metric.details.get("routing_strategy")
            fired_rules = metric.details.get("fired_rules") or []
            if not isinstance(fired_rules, list):
                fired_rules = []
            return (str(strategy) if strategy else None, tuple(str(item) for item in fired_rules))
    return None, ()


def run_generalization_gate(
    *,
    seeds: tuple[int, ...],
    families: tuple[str, ...] | None,
    perturbation_styles: tuple[str, ...] | None = None,
    paraphrase_styles: tuple[str, ...] | None = None,
    service: MemoryService | None = None,
) -> dict[str, Any]:
    if perturbation_styles is None:
        perturbation_styles = paraphrase_styles or QUERY_PERTURBATION_STYLES
    elif paraphrase_styles:
        perturbation_styles = tuple(dict.fromkeys((*perturbation_styles, *paraphrase_styles)))
    service = service or MemoryService(load_settings())
    scenarios = all_scenarios(seeds=seeds)
    if families:
        family_filter = set(families)
        scenarios = [scenario for scenario in scenarios if scenario.family_name in family_filter]
    canonical_results = [run_scenario_instance(service, scenario) for scenario in scenarios]
    perturbed_results = [
        run_scenario_instance(service, scenario_with_perturbation(scenario, style))
        for scenario in scenarios
        for style in perturbation_styles
    ]
    all_results = [*canonical_results, *perturbed_results]

    rows: list[GateRow] = []
    negative_regressions: list[dict[str, Any]] = []
    for result in all_results:
        baseline = _metric_map(result, baseline=True)
        hierarchy = _metric_map(result, baseline=False)
        routing_strategy, fired_rules = _routing_attribution(result)
        row = GateRow(
            family=result.family_name or result.scenario_name,
            variant=_variant_name(result.scenario_name),
            seed=result.seed or 0,
            baseline_keyword=baseline["keyword_recall"],
            baseline_slot=baseline["slot_recall"],
            hierarchy_keyword=hierarchy["keyword_recall"],
            hierarchy_slot=hierarchy["slot_recall"],
            keyword_gain=hierarchy["keyword_recall"] - baseline["keyword_recall"],
            slot_gain=hierarchy["slot_recall"] - baseline["slot_recall"],
            token_delta=baseline["retrieved_token_count"] - hierarchy["retrieved_token_count"],
            winner=_winner(baseline, hierarchy),
            scenario_name=result.scenario_name,
            routing_strategy=routing_strategy,
            fired_rules=fired_rules,
        )
        rows.append(row)
        if row.keyword_gain < 0 or row.slot_gain < 0:
            negative_regressions.append(
                {
                    "family": row.family,
                    "variant": row.variant,
                    "seed": row.seed,
                    "scenario_name": row.scenario_name,
                    "keyword_gain": row.keyword_gain,
                    "slot_gain": row.slot_gain,
                }
            )

    grouped: dict[tuple[str, str], list[GateRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.family, row.variant)].append(row)

    summary_rows: list[dict[str, Any]] = []
    canonical_by_family: dict[str, dict[str, float]] = {}
    for (family, variant), bucket in sorted(grouped.items()):
        kw_gain = statistics.fmean(item.keyword_gain for item in bucket)
        slot_gain = statistics.fmean(item.slot_gain for item in bucket)
        token_delta = statistics.fmean(item.token_delta for item in bucket)
        baseline_kw = statistics.fmean(item.baseline_keyword for item in bucket)
        baseline_slot = statistics.fmean(item.baseline_slot for item in bucket)
        hierarchy_kw = statistics.fmean(item.hierarchy_keyword for item in bucket)
        hierarchy_slot = statistics.fmean(item.hierarchy_slot for item in bucket)
        win_rate = sum(1 for item in bucket if item.winner == "hierarchy") / len(bucket)
        row = {
            "family": family,
            "variant": variant,
            "count": len(bucket),
            "avg_baseline_keyword": baseline_kw,
            "avg_baseline_slot": baseline_slot,
            "avg_hierarchy_keyword": hierarchy_kw,
            "avg_hierarchy_slot": hierarchy_slot,
            "avg_keyword_gain": kw_gain,
            "avg_slot_gain": slot_gain,
            "avg_token_delta": token_delta,
            "hierarchy_win_rate": win_rate,
        }
        summary_rows.append(row)
        if variant == "canonical":
            canonical_by_family[family] = row

    brittle_failures: list[dict[str, Any]] = []
    for row in summary_rows:
        if row["variant"] == "canonical":
            continue
        family = row["family"]
        canonical = canonical_by_family.get(family)
        if canonical is None:
            continue
        # Trigger only when canonical has meaningful gains.
        if canonical["avg_keyword_gain"] <= 0.05 and canonical["avg_slot_gain"] <= 0.05:
            continue
        kw_gain_floor = canonical["avg_keyword_gain"] * 0.6
        slot_gain_floor = canonical["avg_slot_gain"] * 0.6
        kw_recall_floor = canonical["avg_hierarchy_keyword"] * 0.9
        slot_recall_floor = canonical["avg_hierarchy_slot"] * 0.9
        failed_checks: list[str] = []
        if (
            canonical["avg_keyword_gain"] > 0.05
            and row["avg_keyword_gain"] < kw_gain_floor
            and row["avg_hierarchy_keyword"] < kw_recall_floor
        ):
            failed_checks.append("keyword_gain_drop")
        if (
            canonical["avg_slot_gain"] > 0.05
            and row["avg_slot_gain"] < slot_gain_floor
            and row["avg_hierarchy_slot"] < slot_recall_floor
        ):
            failed_checks.append("slot_gain_drop")
        if failed_checks:
            brittle_failures.append(
                {
                    "family": family,
                    "variant": row["variant"],
                    "checks": failed_checks,
                    "canonical_avg_keyword_gain": canonical["avg_keyword_gain"],
                    "canonical_avg_slot_gain": canonical["avg_slot_gain"],
                    "variant_avg_keyword_gain": row["avg_keyword_gain"],
                    "variant_avg_slot_gain": row["avg_slot_gain"],
                }
            )

    rule_utility_rows: list[dict[str, Any]] = []
    by_rule: dict[str, list[GateRow]] = defaultdict(list)
    for row in rows:
        for rule in row.fired_rules:
            by_rule[rule].append(row)
    for rule, bucket in sorted(by_rule.items(), key=lambda item: (-len(item[1]), item[0])):
        rule_utility_rows.append(
            {
                "rule": rule,
                "count": len(bucket),
                "avg_keyword_gain": statistics.fmean(item.keyword_gain for item in bucket),
                "avg_slot_gain": statistics.fmean(item.slot_gain for item in bucket),
                "hierarchy_win_rate": sum(1 for item in bucket if item.winner == "hierarchy") / len(bucket),
                "avg_hierarchy_keyword": statistics.fmean(item.hierarchy_keyword for item in bucket),
                "avg_hierarchy_slot": statistics.fmean(item.hierarchy_slot for item in bucket),
            }
        )
    low_utility_rule_candidates = [
        row
        for row in rule_utility_rows
        if row["count"] >= 5 and row["avg_keyword_gain"] <= 0.0 and row["avg_slot_gain"] <= 0.0
    ]

    strategy_utility_rows: list[dict[str, Any]] = []
    by_strategy: dict[str, list[GateRow]] = defaultdict(list)
    for row in rows:
        if row.routing_strategy:
            by_strategy[row.routing_strategy].append(row)
    for strategy, bucket in sorted(by_strategy.items(), key=lambda item: (-len(item[1]), item[0])):
        strategy_utility_rows.append(
            {
                "strategy": strategy,
                "count": len(bucket),
                "avg_keyword_gain": statistics.fmean(item.keyword_gain for item in bucket),
                "avg_slot_gain": statistics.fmean(item.slot_gain for item in bucket),
                "hierarchy_win_rate": sum(1 for item in bucket if item.winner == "hierarchy") / len(bucket),
            }
        )

    return {
        "report_type": "generalization_gate_report",
        "seeds": list(seeds),
        "perturbation_styles": list(perturbation_styles),
        "summary": {
            "scenario_count": len(rows),
            "negative_regression_count": len(negative_regressions),
            "brittle_failure_count": len(brittle_failures),
            "low_utility_rule_count": len(low_utility_rule_candidates),
            "pass": len(negative_regressions) == 0 and len(brittle_failures) == 0,
        },
        "family_variant_metrics": summary_rows,
        "brittle_failures": brittle_failures,
        "negative_regressions": negative_regressions,
        "rule_utility": rule_utility_rows,
        "low_utility_rule_candidates": low_utility_rule_candidates,
        "strategy_utility": strategy_utility_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unseen-seed + paraphrase generalization gate.")
    parser.add_argument(
        "--seed",
        dest="seeds",
        action="append",
        type=int,
        help="Unseen seeds to test. Repeat for multiple seeds.",
    )
    parser.add_argument(
        "--family",
        dest="families",
        action="append",
        help="Optional scenario family filter. Repeat for multiple families.",
    )
    parser.add_argument(
        "--perturbation-style",
        dest="perturbation_styles",
        action="append",
        choices=list(QUERY_PERTURBATION_STYLES),
        help="Query/scenario perturbation style(s) to include. Repeat for multiple styles.",
    )
    parser.add_argument(
        "--paraphrase-style",
        dest="perturbation_styles",
        action="append",
        choices=list(QUERY_PERTURBATION_STYLES),
        help="Backward-compatible alias for --perturbation-style.",
    )
    args = parser.parse_args()
    seeds = tuple(args.seeds) if args.seeds else tuple(seed + 100 for seed in DEFAULT_SCENARIO_SEEDS)
    families = tuple(args.families) if args.families else None
    perturbation_styles = tuple(args.perturbation_styles) if args.perturbation_styles else QUERY_PERTURBATION_STYLES
    report = run_generalization_gate(seeds=seeds, families=families, perturbation_styles=perturbation_styles)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
