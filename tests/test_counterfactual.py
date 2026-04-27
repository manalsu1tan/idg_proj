from __future__ import annotations

"""Counterfactual replay coverage
Verifies scenario edits replay behavior and api wiring"""

from fastapi.testclient import TestClient

from apps.api.dependencies import get_service
from apps.api.main import app
from packages.evals.counterfactual import (
    apply_counterfactual_operation,
    apply_counterfactual_variant,
    run_counterfactual_replay,
)
from packages.evals.scenarios import relationship_context_scenario
from packages.memory_core.services import MemoryService
from packages.schemas.models import (
    CounterfactualOperation,
    CounterfactualReplayRequest,
    CounterfactualVariantRequest,
    dump_model_json,
)


def test_apply_counterfactual_operations_update_scenario_events() -> None:
    scenario = relationship_context_scenario(11)
    target_text = next(event.text for event in scenario.events if "works best when expectations are sent" in event.text)

    replaced = apply_counterfactual_operation(
        scenario,
        CounterfactualOperation(
            op="replace_event_text",
            match_text=target_text,
            new_text="Reflected that communication works best as a quick live conversation instead.",
        ),
    )
    assert any(event.text == "Reflected that communication works best as a quick live conversation instead." for event in replaced.events)

    inserted = apply_counterfactual_operation(
        replaced,
        CounterfactualOperation(
            op="insert_event_after_day",
            after_day_offset=3,
            text="Inserted counterfactual event after day three.",
            importance_score=0.61,
        ),
    )
    assert any(event.text == "Inserted counterfactual event after day three." and event.day_offset == 4 for event in inserted.events)

    updated_importance = apply_counterfactual_operation(
        inserted,
        CounterfactualOperation(
            op="change_importance",
            match_text="Inserted counterfactual event after day three.",
            importance_score=0.95,
        ),
    )
    inserted_event = next(event for event in updated_importance.events if event.text == "Inserted counterfactual event after day three.")
    assert inserted_event.importance == 0.95

    removed = apply_counterfactual_operation(
        updated_importance,
        CounterfactualOperation(
            op="remove_event",
            match_text="Inserted counterfactual event after day three.",
        ),
    )
    assert all(event.text != "Inserted counterfactual event after day three." for event in removed.events)


def test_apply_counterfactual_variant_changes_identity() -> None:
    scenario = relationship_context_scenario(11)
    variant = CounterfactualVariantRequest(
        variant_id="rewrite-guidance",
        description="Replace durable communication guidance.",
        operations=[
            CounterfactualOperation(
                op="replace_event_text",
                match_text=next(event.text for event in scenario.events if "works best when expectations are sent" in event.text),
                new_text="Reflected that communication works best with an informal verbal sync right before the meeting.",
            )
        ],
    )

    updated = apply_counterfactual_variant(scenario, variant)
    assert updated.name.endswith("__cf_rewrite-guidance")
    assert updated.agent_id.endswith("-cf-rewrite-guidance")
    assert any("informal verbal sync" in event.text for event in updated.events)


def test_counterfactual_replay_reports_variant_deltas(memory_service: MemoryService) -> None:
    scenario = relationship_context_scenario(11)
    target_person = scenario.expected_slots["person"][0].title()
    base_guidance = next(event.text for event in scenario.events if "works best when expectations are sent" in event.text)
    request = CounterfactualReplayRequest(
        scenario_name=scenario.name,
        seed=scenario.seed,
        variants=[
            CounterfactualVariantRequest(
                variant_id="casual-sync",
                description="Swap written pre-read guidance for a last-minute verbal sync.",
                operations=[
                    CounterfactualOperation(
                        op="replace_event_text",
                        match_text=base_guidance,
                        new_text=(
                            f"Reflected that communication with {target_person} works best as a casual live sync "
                            f"right before the meeting, not in writing ahead of time."
                        ),
                    )
                ],
            )
        ],
    )

    report = run_counterfactual_replay(
        request,
        service_factory=lambda: MemoryService(memory_service.settings),
    )

    assert report.report_type == "counterfactual_replay_report"
    assert report.scenario_name == scenario.name
    assert report.base.summary_count >= 1
    assert len(report.variants) == 1
    variant = report.variants[0]
    assert variant.variant_id == "casual-sync"
    assert variant.snapshot.retrieved_signatures
    assert (
        variant.diff.answer_changed
        or variant.diff.added_retrieved_signatures
        or variant.diff.removed_retrieved_signatures
        or variant.diff.retrieved_token_delta != 0
    )
    assert "Counterfactual Replay Report" in report.markdown
    assert "casual-sync" in report.markdown


def test_counterfactual_endpoint_returns_report(memory_service: MemoryService) -> None:
    scenario = relationship_context_scenario(11)
    target_text = next(event.text for event in scenario.events if "works best when expectations are sent" in event.text)
    app.dependency_overrides[get_service] = lambda: memory_service
    client = TestClient(app)
    try:
        response = client.post(
            "/v1/evals/counterfactual/run",
            json=dump_model_json(
                CounterfactualReplayRequest(
                    scenario_name=scenario.name,
                    seed=scenario.seed,
                    variants=[
                        CounterfactualVariantRequest(
                            variant_id="remove-guidance",
                            description="Remove one durable guidance event.",
                            operations=[
                                CounterfactualOperation(
                                    op="remove_event",
                                    match_text=target_text,
                                )
                            ],
                        )
                    ],
                )
            ),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["report_type"] == "counterfactual_replay_report"
        assert payload["scenario_name"] == scenario.name
        assert payload["variants"][0]["variant_id"] == "remove-guidance"
        assert "markdown" in payload
    finally:
        app.dependency_overrides.clear()


def test_counterfactual_invalid_match_raises(memory_service: MemoryService) -> None:
    scenario = relationship_context_scenario(11)
    request = CounterfactualReplayRequest(
        scenario_name=scenario.name,
        seed=scenario.seed,
        variants=[
            CounterfactualVariantRequest(
                variant_id="broken",
                operations=[
                    CounterfactualOperation(
                        op="remove_event",
                        match_text="not a real event",
                    )
                ],
            )
        ],
    )

    try:
        run_counterfactual_replay(request, service_factory=lambda: MemoryService(memory_service.settings))
    except ValueError as exc:
        assert "No scenario event matched text" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected a ValueError for an invalid counterfactual match.")
