from __future__ import annotations

"""Social state digest coverage
Verifies structured fields heuristics and api responses"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from apps.api.dependencies import get_service
from apps.api.main import _seed_stakeholder_handoff_demo_graph, app
from packages.memory_core.services import MemoryService
from packages.schemas.models import BuildSummariesRequest, RefreshRequest


def _all_digest_texts(digest) -> list[str]:
    return [
        *(item.text for item in digest.active_commitments),
        *(item.text for item in digest.active_revisions),
        *(item.text for item in digest.relationship_guidance),
        *(item.text for item in digest.open_tensions),
        *(item.text for item in digest.likely_next_actions),
    ]


def test_social_state_digest_uses_structured_fields(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    node = memory_service.agent_loop.observe(
        "agent-structured",
        "Avery prefers direct feedback and wants concise updates.",
        base,
        0.92,
    )
    node.commitments = ["Send Avery a concise written update."]
    node.revisions = ["Switch from a live sync to an async written summary."]
    node.relationship_guidance = ["Use direct, concise feedback with Avery."]
    node.self_model_updates = ["Draft the written update before noon."]
    memory_service.store.upsert_node(node)

    digest = memory_service.social_state("agent-structured")

    assert any("Send Avery a concise written update." == item.text for item in digest.active_commitments)
    assert any("Switch from a live sync to an async written summary." == item.text for item in digest.active_revisions)
    assert any(item.entity == "Avery" for item in digest.relationship_guidance)
    assert any("Draft the written update before noon." == item.text for item in digest.likely_next_actions)


def test_social_state_digest_surfaces_seeded_demo_guidance_and_tensions(memory_service: MemoryService) -> None:
    stats = _seed_stakeholder_handoff_demo_graph(memory_service, "demo-agent-stakeholder-handoff")
    assert stats["l0_count"] == 14

    digest = memory_service.social_state("demo-agent-stakeholder-handoff")

    guidance_texts = [item.text for item in digest.relationship_guidance]
    revision_texts = [item.text for item in digest.active_revisions]
    tension_texts = [item.text for item in digest.open_tensions]
    action_texts = [item.text for item in digest.likely_next_actions]

    assert any("Sasha" in text and ("written" in text.lower() or "surprise" in text.lower()) for text in guidance_texts)
    assert any("narrated walkthrough" in text.lower() for text in revision_texts)
    assert any("projector" in text.lower() or "risk" in text.lower() for text in tension_texts)
    assert any("Follow-up with Sasha" in text or "Added backup plan" in text for text in action_texts)


def test_social_state_digest_excludes_stale_summaries_from_active_items(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-stale",
        "Maria prefers written expectations before the review.",
        base,
        0.9,
    )
    memory_service.agent_loop.observe(
        "agent-stale",
        "Communication with Maria works best with a written pre-read.",
        base + timedelta(hours=1),
        0.88,
    )
    summaries = memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-stale"))
    assert summaries
    stale_summary = summaries[0]
    memory_service.refresh(
        RefreshRequest(
            agent_id="agent-stale",
            changed_node_ids=[stale_summary.child_ids[0]],
        )
    )

    digest = memory_service.social_state("agent-stale")

    assert digest.stale_summary_count == 1
    assert stale_summary.text not in _all_digest_texts(digest)


def test_social_state_endpoint_returns_digest(memory_service: MemoryService) -> None:
    app.dependency_overrides[get_service] = lambda: memory_service
    client = TestClient(app)
    try:
        seed = client.post(
            "/v1/demo/seed-complex",
            json={
                "scenario_name": "stakeholder_handoff_demo_v1",
                "force": True,
            },
        )
        assert seed.status_code == 200

        response = client.get("/v1/agents/demo-agent-stakeholder-handoff/social-state")
        assert response.status_code == 200
        payload = response.json()
        assert payload["agent_id"] == "demo-agent-stakeholder-handoff"
        assert "relationship_guidance" in payload
        assert "open_tensions" in payload
        assert payload["stale_summary_count"] == 0
    finally:
        app.dependency_overrides.clear()
