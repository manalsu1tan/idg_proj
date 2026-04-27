from __future__ import annotations

"""Batch ingest coverage
Verifies ordering api behavior and source metadata"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.api.dependencies import get_service
from apps.api.main import app
from packages.memory_core.services import MemoryService
from packages.schemas.models import (
    BatchIngestMemoriesRequest,
    IngestMemoryRequest,
    IngestMemoryRecord,
    NodeType,
    dump_model_json,
)


def test_batch_ingest_sorts_records_and_persists_source_metadata(memory_service: MemoryService) -> None:
    response = memory_service.ingest_batch(
        BatchIngestMemoriesRequest(
            agent_id="agent-batch",
            records=[
                IngestMemoryRecord(
                    text="Second event from the imported transcript.",
                    timestamp=datetime(2025, 1, 1, 11, 0, 0),
                    importance_score=0.4,
                    source_type="transcript",
                    source_id="meeting-1",
                    event_id="evt-2",
                ),
                IngestMemoryRecord(
                    text="First event from the imported transcript.",
                    timestamp=datetime(2025, 1, 1, 9, 0, 0),
                    importance_score=0.9,
                    source_type="transcript",
                    source_id="meeting-1",
                    event_id="evt-1",
                ),
            ],
        )
    )

    assert response.received_count == 2
    assert response.ingested_count == 2
    assert response.duplicate_count == 0

    nodes = memory_service.store.list_nodes("agent-batch", include_stale=True)
    assert [node.text for node in nodes] == [
        "First event from the imported transcript.",
        "Second event from the imported transcript.",
    ]
    assert nodes[0].source_type == "transcript"
    assert nodes[0].source_id == "meeting-1"
    assert nodes[0].event_id == "evt-1"
    assert nodes[1].event_id == "evt-2"


def test_batch_ingest_dedupes_existing_event_ids_by_default(memory_service: MemoryService) -> None:
    memory_service.agent_loop.observe(
        "agent-dedupe",
        "Existing note without event metadata.",
        datetime(2025, 1, 1, 8, 0, 0),
        0.2,
    )
    original = memory_service.store.write_l0(
        agent_id="agent-dedupe",
        text="Imported world event already seen.",
        timestamp=datetime(2025, 1, 1, 9, 0, 0),
        importance_score=0.8,
        node_type=NodeType.EPISODE,
        source_type="world_event",
        source_id="world-1",
        event_id="event-1",
    )

    response = memory_service.ingest_batch(
        BatchIngestMemoriesRequest(
            agent_id="agent-dedupe",
            records=[
                IngestMemoryRecord(
                    text="Conflicting duplicate should be ignored.",
                    timestamp=datetime(2025, 1, 1, 10, 0, 0),
                    importance_score=0.5,
                    source_type="world_event",
                    source_id="world-1",
                    event_id="event-1",
                )
            ],
        )
    )

    assert response.received_count == 1
    assert response.ingested_count == 0
    assert response.duplicate_count == 1
    assert response.duplicates == ["event-1"]

    nodes = memory_service.store.list_nodes("agent-dedupe", include_stale=True)
    matching = [node for node in nodes if node.event_id == "event-1"]
    assert len(matching) == 1
    assert matching[0].node_id == original.node_id
    assert matching[0].text == "Imported world event already seen."


def test_batch_ingest_allows_duplicate_event_ids_when_requested(memory_service: MemoryService) -> None:
    response = memory_service.ingest_batch(
        BatchIngestMemoriesRequest(
            agent_id="agent-allow-duplicate",
            records=[
                IngestMemoryRecord(
                    text="Original imported line.",
                    timestamp=datetime(2025, 1, 1, 9, 0, 0),
                    event_id="duplicate-event",
                    allow_duplicate=True,
                ),
                IngestMemoryRecord(
                    text="Replayed imported line.",
                    timestamp=datetime(2025, 1, 1, 10, 0, 0),
                    event_id="duplicate-event",
                    allow_duplicate=True,
                ),
            ],
        )
    )

    assert response.ingested_count == 2
    assert response.duplicate_count == 0
    nodes = memory_service.store.list_nodes("agent-allow-duplicate", include_stale=True)
    matching = [node for node in nodes if node.event_id == "duplicate-event"]
    assert len(matching) == 2


def test_batch_ingest_can_build_summaries_after_ingest(memory_service: MemoryService) -> None:
    response = memory_service.ingest_batch(
        BatchIngestMemoriesRequest(
            agent_id="agent-summaries",
            build_summaries_after_ingest=True,
            records=[
                IngestMemoryRecord(
                    text="Sasha prefers written expectations before the workshop.",
                    timestamp=datetime(2025, 1, 1, 9, 0, 0),
                    importance_score=0.88,
                    event_id="social-1",
                ),
                IngestMemoryRecord(
                    text="Communication with Sasha works best as explicit bullet points in advance.",
                    timestamp=datetime(2025, 1, 1, 10, 0, 0),
                    importance_score=0.9,
                    event_id="social-2",
                ),
            ],
        )
    )

    assert response.ingested_count == 2
    assert response.built_summary_count >= 1
    summaries = memory_service.store.list_nodes("agent-summaries", include_stale=True)
    assert any(node.level.value == "L1" for node in summaries)


def test_single_ingest_endpoint_persists_metadata_and_dedupes_by_event_id(memory_service: MemoryService) -> None:
    app.dependency_overrides[get_service] = lambda: memory_service
    client = TestClient(app)
    try:
        payload = dump_model_json(
            IngestMemoryRequest(
                agent_id="api-single",
                text="Imported transcript line about Maria.",
                timestamp=datetime(2025, 1, 1, 10, 0, 0),
                importance_score=0.9,
                source_type="transcript",
                source_id="meeting-22",
                event_id="meeting-22-line-4",
            )
        )
        first = client.post("/v1/memories/ingest", json=payload)
        second = client.post("/v1/memories/ingest", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["node_id"] == second.json()["node_id"]
        assert first.json()["source_type"] == "transcript"
        assert first.json()["source_id"] == "meeting-22"
        assert first.json()["event_id"] == "meeting-22-line-4"

        timeline = client.get("/v1/agents/api-single/timeline")
        assert timeline.status_code == 200
        nodes = timeline.json()["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["event_id"] == "meeting-22-line-4"
    finally:
        app.dependency_overrides.clear()


def test_batch_ingest_endpoint_returns_duplicate_details_and_builds_summaries(memory_service: MemoryService) -> None:
    app.dependency_overrides[get_service] = lambda: memory_service
    client = TestClient(app)
    try:
        seed = client.post(
            "/v1/memories/ingest",
            json=dump_model_json(
                IngestMemoryRequest(
                    agent_id="api-batch",
                    text="Already imported event.",
                    timestamp=datetime(2025, 1, 1, 8, 0, 0),
                    event_id="existing-event",
                )
            ),
        )
        assert seed.status_code == 200

        batch = client.post(
            "/v1/memories/ingest/batch",
            json=dump_model_json(
                BatchIngestMemoriesRequest(
                    agent_id="api-batch",
                    build_summaries_after_ingest=True,
                    records=[
                        IngestMemoryRecord(
                            text="This duplicate should be skipped.",
                            timestamp=datetime(2025, 1, 1, 9, 0, 0),
                            event_id="existing-event",
                        ),
                        IngestMemoryRecord(
                            text="Sasha wants the final talking points in writing.",
                            timestamp=datetime(2025, 1, 1, 10, 0, 0),
                            importance_score=0.91,
                            source_type="transcript",
                            source_id="meeting-5",
                            event_id="meeting-5-line-10",
                        ),
                        IngestMemoryRecord(
                            text="Do not surprise Sasha with day-of format changes.",
                            timestamp=datetime(2025, 1, 1, 11, 0, 0),
                            importance_score=0.9,
                            source_type="transcript",
                            source_id="meeting-5",
                            event_id="meeting-5-line-11",
                        ),
                    ],
                )
            ),
        )

        assert batch.status_code == 200
        payload = batch.json()
        assert payload["received_count"] == 3
        assert payload["ingested_count"] == 2
        assert payload["duplicate_count"] == 1
        assert payload["duplicates"] == ["existing-event"]
        assert payload["built_summary_count"] >= 1

        tree = client.get("/v1/agents/api-batch/tree")
        assert tree.status_code == 200
        assert tree.json()["roots"]
    finally:
        app.dependency_overrides.clear()


def test_batch_ingest_endpoint_accepts_offset_aware_timestamps(memory_service: MemoryService) -> None:
    app.dependency_overrides[get_service] = lambda: memory_service
    client = TestClient(app)
    try:
        batch = client.post(
            "/v1/memories/ingest/batch",
            json={
                "agent_id": "api-aware",
                "records": [
                    {
                        "text": "Imported offset-aware event.",
                        "timestamp": "2025-01-01T10:00:00+02:00",
                        "importance_score": 0.8,
                        "event_id": "aware-1",
                    },
                    {
                        "text": "Imported naive event.",
                        "timestamp": "2025-01-01T07:30:00",
                        "importance_score": 0.5,
                        "event_id": "naive-1",
                    },
                ],
            },
        )

        assert batch.status_code == 200
        timeline = client.get("/v1/agents/api-aware/timeline")
        assert timeline.status_code == 200
        nodes = timeline.json()["nodes"]
        assert [node["event_id"] for node in nodes] == ["naive-1", "aware-1"]
        assert nodes[1]["timestamp_start"] == "2025-01-01T08:00:00"
    finally:
        app.dependency_overrides.clear()
