from __future__ import annotations

import argparse
import json

from packages.evals.scenarios import all_scenarios
from packages.evals.runner import run_scenario
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import load_settings


def reset_benchmark_agents(service: MemoryService) -> list[str]:
    removed: list[str] = []
    for scenario in all_scenarios():
        nodes = service.store.list_nodes(agent_id=scenario.agent_id, include_stale=True)
        if not nodes:
            continue
        service.store.delete_agent_data(scenario.agent_id)
        removed.append(scenario.agent_id)
    return removed


def seed_benchmark_agents(reset: bool = False) -> list[dict]:
    service = MemoryService(load_settings())
    removed = reset_benchmark_agents(service) if reset else []
    seeded: list[dict] = []
    for scenario in all_scenarios():
        result = run_scenario(service, scenario.name)
        seeded.append(
            {
                "agent_id": scenario.agent_id,
                "scenario_name": scenario.name,
                "notes": scenario.notes,
                "result": {
                    "baseline_keyword_recall": next(metric.value for metric in result.baseline_metrics if metric.name == "keyword_recall"),
                    "hierarchy_keyword_recall": next(metric.value for metric in result.hierarchy_metrics if metric.name == "keyword_recall"),
                },
            }
        )
    return [{"removed_agents": removed}, *seeded]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed benchmark agents into the configured database.")
    parser.add_argument("--reset", action="store_true", help="Delete existing benchmark-agent data before reseeding.")
    args = parser.parse_args()
    print(json.dumps(seed_benchmark_agents(reset=args.reset), indent=2))


if __name__ == "__main__":
    main()
