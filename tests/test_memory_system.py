from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.dependencies import get_service
from packages.memory_core.model_components import ModelBackedSummarizer
from packages.memory_core.model_clients import MockModelClient
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import Settings
from packages.schemas.models import ModelProvider
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
    assert "prototype" in summaries[0].text.lower()


def test_builds_singleton_summary_for_pivotal_event(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-singleton",
        "Updated the plan: the prototype now ships Friday after QA.",
        base,
        0.96,
    )
    summaries = memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-singleton"))
    assert len(summaries) == 1
    assert summaries[0].child_ids
    assert summaries[0].token_count <= memory_service.settings.summary_max_tokens
    assert "friday" in summaries[0].text.lower()


def test_commitment_queries_use_flat_router_for_best_leaf(memory_service: MemoryService) -> None:
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
    assert hierarchical.packed_context == flat.packed_context
    assert hierarchical.retrieval_depth == 1
    assert all(item.selected_as == "query_router_flat" for item in hierarchical.retrieved_nodes)


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




def test_balanced_retrieval_prefers_summary_without_duplicate_leaf_drilldown(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-branch",
        "Met Maria and promised to bring the prototype to the Friday demo.",
        base,
        0.95,
    )
    memory_service.agent_loop.observe(
        "agent-branch",
        "Reflected that Maria only needs the finished prototype, not the draft.",
        base + timedelta(hours=1),
        0.88,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-branch"))
    response = memory_service.retrieve(
        agent_id="agent-branch",
        query="What is my commitment to Maria for the Friday demo?",
        query_time=base + timedelta(days=1),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=2,
    )
    selected_as = {item.selected_as for item in response.retrieved_nodes}
    assert "summary" in selected_as
    assert response.diagnostics.supporting_leaf_count == 0


def test_detail_queries_descend_instead_of_packing_summary_and_leaf(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-detail",
        "Maria changed the ask and now wants the finished prototype at the Friday demo.",
        base,
        0.95,
    )
    memory_service.agent_loop.observe(
        "agent-detail",
        "The earlier draft version is obsolete after Maria's update.",
        base + timedelta(hours=1),
        0.9,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-detail"))
    response = memory_service.retrieve(
        agent_id="agent-detail",
        query="What changed in Maria's latest request?",
        query_time=base + timedelta(days=1),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=2,
    )
    selected_as = {item.selected_as for item in response.retrieved_nodes}
    assert "supporting_leaf" in selected_as
    assert "summary" not in selected_as


def test_commitment_queries_route_to_flat_top1(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-commitment-router",
        "Met Maria and promised to bring the finished prototype to the Friday demo.",
        base,
        0.95,
    )
    memory_service.agent_loop.observe(
        "agent-commitment-router",
        "Wrote a prep checklist for meeting Maria at the Friday demo: pack the finished prototype, badge, and charger.",
        base + timedelta(hours=1),
        0.72,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-commitment-router"))
    response = memory_service.retrieve(
        agent_id="agent-commitment-router",
        query="What commitment did I make to Maria about the Friday demo?",
        query_time=base + timedelta(days=1),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=3,
    )
    assert response.retrieval_depth == 1
    assert response.diagnostics.summary_node_count == 0
    assert response.diagnostics.retrieved_node_count == 1
    assert all(item.selected_as == "query_router_flat" for item in response.retrieved_nodes)


def test_conflict_queries_descend_for_specific_event_details(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-conflict",
        "Had a tense argument with Jordan about a missed handoff and agreed to repair trust tomorrow.",
        base,
        0.95,
    )
    memory_service.agent_loop.observe(
        "agent-conflict",
        "Reflected that the conflict with Jordan was serious because the handoff failed in public.",
        base + timedelta(hours=1),
        0.88,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-conflict"))
    response = memory_service.retrieve(
        agent_id="agent-conflict",
        query="What major conflict happened recently and with whom?",
        query_time=base + timedelta(days=1),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=2,
    )
    assert response.diagnostics.supporting_leaf_count >= 1
    assert any(item.selected_as == "supporting_leaf" for item in response.retrieved_nodes)


def test_revision_queries_can_span_multiple_branches(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe("agent-revision", "Committed to shipping the prototype on Thursday.", base, 0.9)
    memory_service.agent_loop.observe("agent-revision", "Updated the plan: the prototype will ship on Friday after extra QA.", base + timedelta(days=3), 0.95)
    memory_service.agent_loop.observe("agent-revision", "Told the team that Friday is the correct launch date now.", base + timedelta(days=4), 0.88)
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-revision"))
    response = memory_service.retrieve(
        agent_id="agent-revision",
        query="When is the prototype actually supposed to ship now?",
        query_time=base + timedelta(days=5),
        mode=QueryMode.BALANCED,
        token_budget=90,
        branch_limit=3,
    )
    assert response.diagnostics.branch_count >= 1
    assert response.diagnostics.supporting_leaf_count >= 1


def test_general_query_flat_fallback_is_cheap(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    for index in range(3):
        memory_service.agent_loop.observe(
            "agent-fallback",
            f"Important meeting {index} about roadmap priorities and team staffing.",
            base + timedelta(hours=index),
            0.8,
        )
    response = memory_service.retrieve(
        agent_id="agent-fallback",
        query="What important meeting happened?",
        query_time=base + timedelta(days=1),
        mode=QueryMode.BALANCED,
        token_budget=80,
        branch_limit=3,
    )
    assert response.diagnostics.fallback_used is True
    assert response.diagnostics.retrieved_node_count == 1


def test_social_and_identity_clusters_get_wider_summary_cap() -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        model_provider="mock",
        summary_max_tokens=8,
        social_summary_max_tokens=14,
    )
    summarizer = ModelBackedSummarizer(MockModelClient(), ModelProvider.MOCK, settings)
    service = MemoryService(settings)
    base = datetime(2025, 1, 1, 9, 0, 0)
    social_node = service.agent_loop.observe(
        "agent-social",
        "Avery prefers direct feedback and hates surprise meetings.",
        base,
        0.9,
    )
    neutral_node = service.agent_loop.observe(
        "agent-neutral",
        "Reviewed sprint metrics and updated the dashboard.",
        base + timedelta(hours=1),
        0.4,
    )
    assert summarizer._summary_token_cap([social_node]) == 14
    assert summarizer._summary_token_cap([neutral_node]) == 8


def test_identity_queries_remain_on_hierarchy_path(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-hierarchy-identity",
        "Used to identify as a backend engineer who avoids presenting.",
        base,
        0.7,
    )
    memory_service.agent_loop.observe(
        "agent-hierarchy-identity",
        "Reflected that I now enjoy presenting research demos and should lean into that role.",
        base + timedelta(days=5),
        0.94,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-hierarchy-identity"))
    response = memory_service.retrieve(
        agent_id="agent-hierarchy-identity",
        query="How do I describe my current relationship to presenting or facilitation?",
        query_time=base + timedelta(days=10),
        mode=QueryMode.BALANCED,
        token_budget=90,
        branch_limit=3,
    )
    assert all(item.selected_as != "query_router_flat" for item in response.retrieved_nodes)


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
