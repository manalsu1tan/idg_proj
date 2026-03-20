from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.dependencies import get_service
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import Settings
from packages.schemas.models import BuildSummariesRequest, IngestMemoryRequest, QueryMode, RefreshRequest, dump_model_json


def test_builds_traceable_summaries(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe("agent-1", "Met Maria and promised to bring the prototype.", base, 0.9)
    memory_service.agent_loop.observe("agent-1", "Reflected that Maria's prototype request is urgent.", base + timedelta(hours=1), 0.8)
    summaries = memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-1"))
    assert len(summaries) == 1
    provenance = memory_service.node_provenance(summaries[0].node_id)
    assert len(provenance.supports) == 2
    assert set(summaries[0].support_ids) == {node.node_id for node in provenance.supports}


def test_hierarchy_beats_flat_recall(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-2",
        "Met Maria and promised to bring the finished item to the Friday Simile AI demo.",
        base,
        0.95,
    )
    memory_service.agent_loop.observe(
        "agent-2",
        "Planned that the promised item for Maria is the finished prototype for Friday.",
        base + timedelta(hours=1),
        0.92,
    )
    for day in range(2, 14):
        memory_service.agent_loop.observe(
            "agent-2",
            f"Day {day} routine: reviewed dashboard metrics and ate lunch at the office.",
            base + timedelta(days=day),
            0.2,
        )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-2"))
    query_time = base + timedelta(days=14)
    flat = memory_service.retrieve_flat(
        agent_id="agent-2",
        query="What did I promise Maria to bring for the Simile AI demo?",
        query_time=query_time,
        token_budget=70,
        branch_limit=1,
    )
    hierarchical = memory_service.retrieve(
        agent_id="agent-2",
        query="What did I promise Maria to bring for the Simile AI demo?",
        query_time=query_time,
        mode=QueryMode.BALANCED,
        token_budget=70,
        branch_limit=2,
    )
    assert "prototype" not in flat.packed_context.lower()
    assert "prototype" in hierarchical.packed_context.lower()
    assert hierarchical.retrieval_depth >= 1


def test_refresh_marks_parent_stale(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    first = memory_service.agent_loop.observe("agent-3", "Talked with Jordan about missed handoff.", base, 0.9)
    memory_service.agent_loop.observe("agent-3", "Agreed to repair trust tomorrow.", base + timedelta(hours=1), 0.8)
    summaries = memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-3"))
    stale = memory_service.refresh(RefreshRequest(agent_id="agent-3", changed_node_ids=[first.node_id]))
    assert stale
    assert stale[0].node_id == summaries[0].node_id
    assert memory_service.store.get_node(summaries[0].node_id).stale_flag is True


def test_context_pack_respects_budget(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    for index in range(5):
        memory_service.agent_loop.observe(
            "agent-4",
            f"Important event {index} with many descriptive details about design reviews and coordination.",
            base + timedelta(hours=index),
            0.9,
        )
    response = memory_service.retrieve_flat(
        agent_id="agent-4",
        query="What happened in the design review?",
        query_time=base + timedelta(days=1),
        token_budget=20,
        branch_limit=5,
    )
    assert len(response.packed_context.split()) <= 25


def test_api_endpoints(memory_service: MemoryService) -> None:
    app.dependency_overrides[get_service] = lambda: memory_service
    client = TestClient(app)
    response = client.post(
        "/v1/memories/ingest",
        json=dump_model_json(
            IngestMemoryRequest(
            agent_id="api-agent",
            text="Observed a critical meeting with Maria.",
            timestamp=datetime(2025, 1, 1, 10, 0, 0),
            importance_score=0.9,
            )
        ),
    )
    assert response.status_code == 200
    build = client.post(
        "/v1/summaries/build",
        json=dump_model_json(BuildSummariesRequest(agent_id="api-agent")),
    )
    assert build.status_code == 200
    retrieve = client.post(
        "/v1/memories/retrieve",
        json={
            "agent_id": "api-agent",
            "query": "What happened with Maria?",
            "query_time": "2025-01-02T10:00:00",
            "mode": "balanced",
            "token_budget": 80,
            "branch_limit": 2,
        },
    )
    assert retrieve.status_code == 200
    traces = client.get("/v1/retrievals?agent_id=api-agent&limit=5")
    assert traces.status_code == 200
    tree = client.get("/v1/agents/api-agent/tree")
    assert tree.status_code == 200
    ui = client.get("/ui")
    assert ui.status_code == 200
    app.dependency_overrides.clear()


def test_retrieve_accepts_offset_aware_query_time(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe("agent-aware", "Met Maria and promised to bring the prototype.", base, 0.9)
    memory_service.agent_loop.observe("agent-aware", "Planned that the promised item is the prototype.", base + timedelta(hours=1), 0.8)
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-aware"))
    response = memory_service.retrieve(
        agent_id="agent-aware",
        query="What did I promise to bring?",
        query_time=datetime(2025, 1, 2, 9, 0, 0, tzinfo=timezone.utc),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=2,
    )
    assert response.retrieved_nodes
    assert response.diagnostics.retrieved_node_count >= 1
    assert response.diagnostics.packed_token_count >= 1
