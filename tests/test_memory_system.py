from __future__ import annotations

"""Test module overview for test memory system
Covers behavior and regression checks"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.dependencies import get_service
from packages.memory_core.model_components import ModelBackedSummarizer
from packages.memory_core.model_clients import MockModelClient
import packages.memory_core.services as services_module
from packages.memory_core.services import MemoryService
from packages.memory_core.settings import Settings
from packages.memory_core.storage import Database as RealDatabase
from sqlalchemy.exc import OperationalError
from packages.schemas.models import ModelProvider, QualityStatus
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
        "Met Maria and promised to bring the finished item to the Friday Smile demo.",
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
        query="What did I promise Maria to bring for the Smile demo?",
        query_time=query_time,
        token_budget=70,
        branch_limit=1,
    )
    hierarchical = memory_service.retrieve(
        agent_id="agent-2",
        query="What did I promise Maria to bring for the Smile demo?",
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


def test_service_falls_back_to_sqlite_when_postgres_is_unavailable(tmp_path, monkeypatch) -> None:
    fallback_path = tmp_path / "fallback.sqlite3"

    class FakeDatabase:
        def __init__(self, url: str) -> None:
            self.url = url
            self._delegate = None if url.startswith("postgresql") else RealDatabase(url)

        def verify_connection(self) -> None:
            if self.url.startswith("postgresql"):
                raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))
            assert self._delegate is not None
            self._delegate.verify_connection()

        def create_all(self) -> None:
            assert self._delegate is not None
            self._delegate.create_all()

        def session(self):
            assert self._delegate is not None
            return self._delegate.session()

    monkeypatch.setattr(services_module, "Database", FakeDatabase)

    service = MemoryService(
        Settings(
            database_url="postgresql+psycopg://project_b:project_b@localhost:5432/project_b",
            database_fallback_url=f"sqlite+pysqlite:///{fallback_path}",
            database_fallback_on_unavailable=True,
            auto_create_schema=False,
            model_provider="mock",
        )
    )

    assert service.store.list_nodes("missing-agent", include_stale=True) == []




def test_balanced_retrieval_prefers_leaf_first_when_single_leaf_is_enough(memory_service: MemoryService) -> None:
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
    assert "query_router_flat" in selected_as
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


def test_cross_event_composition_query_collects_multiple_supporting_leaves(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-composition-coverage",
        "In 1:1, Avery said they prefer direct feedback.",
        base,
        0.83,
    )
    memory_service.agent_loop.observe(
        "agent-composition-coverage",
        "Later, learned Avery dislikes surprise meetings.",
        base + timedelta(days=1),
        0.82,
    )
    memory_service.agent_loop.observe(
        "agent-composition-coverage",
        "Reflection: with Avery, I should send bullet points in advance.",
        base + timedelta(days=3),
        0.9,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-composition-coverage"))
    response = memory_service.retrieve(
        agent_id="agent-composition-coverage",
        query="How should I communicate with Avery given their preferences and dislikes?",
        query_time=base + timedelta(days=5),
        mode=QueryMode.BALANCED,
        token_budget=120,
        branch_limit=3,
    )
    assert response.retrieval_depth >= 2
    assert response.diagnostics.supporting_leaf_count >= 2
    packed = response.packed_context.lower()
    assert "prefer" in packed
    assert "dislike" in packed
    assert "should" in packed


def test_social_thread_builder_clusters_person_threads_into_l1_branches(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-social-threads",
        "Sasha prefers written agendas and dislikes surprises.",
        base,
        0.86,
    )
    memory_service.agent_loop.observe(
        "agent-social-threads",
        "Leah prefers informal check-ins and casual syncs.",
        base + timedelta(days=1),
        0.82,
    )
    memory_service.agent_loop.observe(
        "agent-social-threads",
        "Follow-up: with Sasha, send expectations in writing first.",
        base + timedelta(days=2),
        0.88,
    )
    memory_service.agent_loop.observe(
        "agent-social-threads",
        "Follow-up: with Leah, improv sessions are fine.",
        base + timedelta(days=3),
        0.76,
    )
    summaries = memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-social-threads"))
    assert len(summaries) == 2
    child_texts = [
        {memory_service.store.get_node(child_id).text for child_id in summary.child_ids}
        for summary in summaries
    ]
    assert any(
        {
            "Sasha prefers written agendas and dislikes surprises.",
            "Follow-up: with Sasha, send expectations in writing first.",
        }
        == texts
        for texts in child_texts
    )
    assert any(
        {
            "Leah prefers informal check-ins and casual syncs.",
            "Follow-up: with Leah, improv sessions are fine.",
        }
        == texts
        for texts in child_texts
    )


def test_multi_person_comparison_query_collects_both_person_threads(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    agent_id = "agent-multi-person-compare"
    memory_service.agent_loop.observe(
        agent_id,
        "Sasha prefers written agendas and dislikes surprises.",
        base,
        0.86,
    )
    memory_service.agent_loop.observe(
        agent_id,
        "Leah prefers informal check-ins and casual syncs.",
        base + timedelta(days=1),
        0.82,
    )
    memory_service.agent_loop.observe(
        agent_id,
        "Follow-up: with Sasha, send expectations in writing first.",
        base + timedelta(days=2),
        0.88,
    )
    memory_service.agent_loop.observe(
        agent_id,
        "Follow-up: with Leah, improv sessions are fine.",
        base + timedelta(days=3),
        0.76,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id=agent_id))
    query = "How should I approach Sasha differently from Leah?"
    balanced = memory_service.retrieve(
        agent_id=agent_id,
        query=query,
        query_time=base + timedelta(days=5),
        mode=QueryMode.BALANCED,
        token_budget=120,
        branch_limit=3,
    )
    drill_down = memory_service.retrieve(
        agent_id=agent_id,
        query=query,
        query_time=base + timedelta(days=5),
        mode=QueryMode.DRILL_DOWN,
        token_budget=120,
        branch_limit=3,
    )
    for response in (balanced, drill_down):
        packed = response.packed_context.lower()
        assert "sasha" in packed
        assert "leah" in packed
        assert response.diagnostics.retrieved_node_count >= 2
    assert all(item.selected_as != "query_router_flat" for item in balanced.retrieved_nodes)


def test_retrieve_generates_grounded_answer_from_retrieved_context(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 2, 9, 0, 0)
    agent_id = "agent-answer"
    memory_service.agent_loop.observe(
        agent_id,
        "Sasha prefers written agendas and dislikes surprises.",
        base,
        0.86,
    )
    memory_service.agent_loop.observe(
        agent_id,
        "Follow-up: with Sasha, send expectations in writing first.",
        base + timedelta(days=1),
        0.88,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id=agent_id))
    response = memory_service.retrieve(
        agent_id=agent_id,
        query="What communication strategy should I use with Sasha?",
        query_time=base + timedelta(days=3),
        mode=QueryMode.DRILL_DOWN,
        token_budget=120,
        branch_limit=3,
    )
    assert response.answer is not None
    assert response.answer.text
    assert response.answer.citations
    assert "sasha" in response.answer.text.lower()


def test_retrieve_can_optionally_verify_generated_answer(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 2, 9, 0, 0)
    agent_id = "agent-answer-verify"
    memory_service.agent_loop.observe(
        agent_id,
        "Sasha prefers written agendas and dislikes surprises.",
        base,
        0.86,
    )
    memory_service.agent_loop.observe(
        agent_id,
        "Follow-up: with Sasha, send expectations in writing first.",
        base + timedelta(days=1),
        0.88,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id=agent_id))
    response = memory_service.retrieve(
        agent_id=agent_id,
        query="What evidence supports sending Sasha written expectations first?",
        query_time=base + timedelta(days=3),
        mode=QueryMode.DRILL_DOWN,
        token_budget=120,
        branch_limit=3,
        verify_answer=True,
    )
    assert response.answer is not None
    assert response.answer_verification is not None
    assert response.answer_verification.quality_status == QualityStatus.VERIFIED
    traces = memory_service.model_traces(agent_id=agent_id)
    components = {trace.component for trace in traces}
    assert "answerer" in components
    assert "answer_verifier" in components
    by_component = {trace.component: trace for trace in traces}
    assert by_component["answerer"].node_id is not None
    assert by_component["answerer"].node_id in response.answer.citations
    assert by_component["answer_verifier"].node_id is not None
    assert by_component["answer_verifier"].node_id in {
        item.node.node_id for item in response.retrieved_nodes
    }


def test_negation_sensitive_agreement_query_adds_polarity_support(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-negation-coverage",
        "I did not agree to bring the demo kit for Maria.",
        base,
        0.86,
    )
    memory_service.agent_loop.observe(
        "agent-negation-coverage",
        "I agreed to bring the finished prototype for the Friday demo.",
        base + timedelta(days=1),
        0.92,
    )
    memory_service.agent_loop.observe(
        "agent-negation-coverage",
        "Checklist: do not pack the demo kit; pack the finished prototype.",
        base + timedelta(days=2),
        0.88,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-negation-coverage"))
    response = memory_service.retrieve(
        agent_id="agent-negation-coverage",
        query="What did I agree to bring for Maria at the Friday demo?",
        query_time=base + timedelta(days=4),
        mode=QueryMode.BALANCED,
        token_budget=120,
        branch_limit=3,
    )
    assert response.retrieval_depth >= 2
    assert response.diagnostics.supporting_leaf_count >= 2
    packed = response.packed_context.lower()
    assert "finished prototype" in packed
    assert "maria" in packed


def test_delayed_commitment_query_collects_commitment_and_item_details(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-delayed-commitment-coverage",
        "Met Maria and promised I would bring it for their upcoming request.",
        base,
        0.95,
    )
    memory_service.agent_loop.observe(
        "agent-delayed-commitment-coverage",
        "Follow-up note: for the Friday product demo, the item to bring is the finished prototype.",
        base,
        0.9,
    )
    memory_service.agent_loop.observe(
        "agent-delayed-commitment-coverage",
        "Day 7 routine: reviewed dashboard metrics and ate lunch at the office.",
        base + timedelta(days=6),
        0.2,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-delayed-commitment-coverage"))
    response = memory_service.retrieve(
        agent_id="agent-delayed-commitment-coverage",
        query="For the Friday product demo, which item did I commit to bringing for Maria?",
        query_time=base + timedelta(days=10),
        mode=QueryMode.BALANCED,
        token_budget=120,
        branch_limit=3,
    )
    assert response.retrieval_depth >= 2
    assert response.diagnostics.supporting_leaf_count >= 2
    packed = response.packed_context.lower()
    assert "promised" in packed
    assert "finished prototype" in packed


def test_revision_queries_use_leaf_first_when_top_leaf_has_revision_cues(memory_service: MemoryService) -> None:
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
    assert response.retrieval_depth == 1
    assert response.diagnostics.branch_count == 0
    assert response.diagnostics.supporting_leaf_count == 0
    assert response.diagnostics.retrieved_node_count <= 2
    assert all(item.selected_as == "query_router_flat" for item in response.retrieved_nodes)
    assert "friday" in response.packed_context.lower()


def test_revision_queries_expand_when_top_leaf_lacks_override_cues(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe("agent-revision-expand", "Committed to shipping the prototype on Thursday.", base, 0.9)
    memory_service.agent_loop.observe("agent-revision-expand", "Shipping plan says prototype on Friday after QA.", base + timedelta(days=3), 0.96)
    memory_service.agent_loop.observe("agent-revision-expand", "Team note confirms Friday launch date.", base + timedelta(days=4), 0.88)
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-revision-expand"))
    response = memory_service.retrieve(
        agent_id="agent-revision-expand",
        query="When is the prototype actually supposed to ship now?",
        query_time=base + timedelta(days=5),
        mode=QueryMode.BALANCED,
        token_budget=90,
        branch_limit=3,
    )
    assert response.retrieval_depth >= 1
    assert response.diagnostics.branch_count <= 2
    assert "friday" in response.packed_context.lower()


def test_commitment_revision_query_stays_leaf_first_when_latest_leaf_is_sufficient(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe("agent-commitment-revision", "Committed to shipping the prototype on Thursday.", base, 0.9)
    memory_service.agent_loop.observe(
        "agent-commitment-revision",
        "Updated the plan: the prototype will ship on Friday after final QA.",
        base + timedelta(days=2),
        0.97,
    )
    memory_service.agent_loop.observe(
        "agent-commitment-revision",
        "Confirmed Friday is now the current launch date for the prototype.",
        base + timedelta(days=3),
        0.9,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-commitment-revision"))
    response = memory_service.retrieve(
        agent_id="agent-commitment-revision",
        query="When is the prototype actually supposed to ship now?",
        query_time=base + timedelta(days=4),
        mode=QueryMode.BALANCED,
        token_budget=90,
        branch_limit=3,
    )
    assert response.retrieval_depth == 1
    assert response.diagnostics.retrieved_node_count <= 2
    assert response.diagnostics.branch_count == 0
    assert all(item.selected_as == "query_router_flat" for item in response.retrieved_nodes)
    assert "friday" in response.packed_context.lower()


def test_revision_query_keeps_leaf_first_when_low_confidence_but_top_leaf_has_cues(
    memory_service: MemoryService, monkeypatch
) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    agent_id = "agent-commitment-revision-low-confidence"
    query = "When is the prototype actually supposed to ship now?"
    query_time = base + timedelta(days=4)
    memory_service.agent_loop.observe(
        agent_id,
        "Updated launch plan: the prototype now ships Friday after final QA.",
        base + timedelta(days=2),
        0.95,
    )
    memory_service.agent_loop.observe(
        agent_id,
        "Prototype ships Friday after final QA according to the schedule.",
        base + timedelta(days=2),
        0.95,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id=agent_id))

    retriever = memory_service.hierarchical_retriever
    ranked = retriever._rank_leaf_candidates(agent_id, query, query_time)[:2]
    assert len(ranked) == 2
    assert retriever._leaf_satisfies_revision_slot_cues(query, ranked[0].node.text)
    monkeypatch.setattr(retriever, "_is_low_confidence", lambda _: True)

    response = memory_service.retrieve(
        agent_id=agent_id,
        query=query,
        query_time=query_time,
        mode=QueryMode.BALANCED,
        token_budget=90,
        branch_limit=3,
    )
    assert response.retrieval_depth == 1
    assert response.diagnostics.branch_count == 0
    assert all(item.selected_as == "query_router_flat" for item in response.retrieved_nodes)
    assert "friday" in response.packed_context.lower()


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
    assert response.diagnostics.retrieved_node_count == 1
    assert response.diagnostics.summary_node_count == 0
    assert response.diagnostics.fallback_used or all(
        item.selected_as == "query_router_flat" for item in response.retrieved_nodes
    )


def test_non_detail_queries_short_circuit_to_leaf_first(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-leaf-first",
        "Important: Avery consistently prefers written agendas for serious work updates.",
        base,
        0.9,
    )
    memory_service.agent_loop.observe(
        "agent-leaf-first",
        "Recent note: Avery changed office snack preference today.",
        base + timedelta(days=8),
        0.35,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-leaf-first"))
    response = memory_service.retrieve(
        agent_id="agent-leaf-first",
        query="Remind me of Avery's stable preference for serious updates.",
        query_time=base + timedelta(days=10),
        mode=QueryMode.BALANCED,
        token_budget=90,
        branch_limit=3,
    )
    assert response.retrieval_depth == 1
    assert response.diagnostics.retrieved_node_count == 1
    assert all(item.selected_as == "query_router_flat" for item in response.retrieved_nodes)


def test_temporal_latest_queries_avoid_multi_branch_expansion(memory_service: MemoryService) -> None:
    base = datetime(2025, 1, 1, 9, 0, 0)
    memory_service.agent_loop.observe(
        "agent-temporal-cap",
        "Initial plan: ship the prototype on Tuesday.",
        base,
        0.7,
    )
    memory_service.agent_loop.observe(
        "agent-temporal-cap",
        "Revision: move prototype shipping to Wednesday.",
        base + timedelta(days=2),
        0.78,
    )
    memory_service.agent_loop.observe(
        "agent-temporal-cap",
        "Final decision: ship the prototype on Friday after final QA.",
        base + timedelta(days=5),
        0.95,
    )
    memory_service.agent_loop.observe(
        "agent-temporal-cap",
        "Shared with the team that Friday is the canonical launch date.",
        base + timedelta(days=6),
        0.88,
    )
    memory_service.build_summaries(BuildSummariesRequest(agent_id="agent-temporal-cap"))
    response = memory_service.retrieve(
        agent_id="agent-temporal-cap",
        query="What is the latest committed ship day for the prototype?",
        query_time=base + timedelta(days=8),
        mode=QueryMode.BALANCED,
        token_budget=120,
        branch_limit=3,
    )
    assert response.diagnostics.branch_count <= 1
    assert response.diagnostics.retrieved_node_count <= 1
    assert "friday" in response.packed_context.lower()


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


def test_demo_seed_endpoint_populates_stakeholder_handoff_scenario(memory_service: MemoryService) -> None:
    app.dependency_overrides[get_service] = lambda: memory_service
    client = TestClient(app)
    seed = client.post(
        "/v1/demo/seed-complex",
        json={
            "scenario_name": "stakeholder_handoff_demo_v1",
            "force": True,
        },
    )
    assert seed.status_code == 200
    payload = seed.json()
    assert payload["seeded"] is True
    assert payload["agent_id"] == "demo-agent-stakeholder-handoff"
    assert payload["scenario_name"] == "stakeholder_handoff_demo_v1"
    assert payload["l0_count"] == 14
    assert payload["l1_count"] == 4
    assert payload["l2_count"] == 1
    assert len(payload["query_presets"]) >= 6

    timeline = client.get("/v1/agents/demo-agent-stakeholder-handoff/timeline")
    assert timeline.status_code == 200
    nodes = timeline.json()["nodes"]
    assert any("Sasha asked for a written agenda" in node["text"] for node in nodes)
    assert any("narrated walkthrough" in node["text"] for node in nodes)
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
