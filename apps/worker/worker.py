from __future__ import annotations

from packages.memory_core.bootstrap import get_memory_service
from packages.schemas.models import dump_model
from packages.schemas.models import BuildSummariesRequest, RefreshRequest


def build_summaries_job(agent_id: str) -> list[dict]:
    service = get_memory_service()
    nodes = service.build_summaries(BuildSummariesRequest(agent_id=agent_id))
    return [dump_model(node) for node in nodes]


def refresh_job(agent_id: str, changed_node_ids: list[str]) -> list[dict]:
    service = get_memory_service()
    nodes = service.refresh(RefreshRequest(agent_id=agent_id, changed_node_ids=changed_node_ids))
    return [dump_model(node) for node in nodes]


def verify_job(node_id: str) -> dict | None:
    service = get_memory_service()
    node = service.store.get_node(node_id)
    if node is None:
        return None
    supports = [service.store.get_node(item) for item in node.support_ids]
    result, trace = service.verifier.verify(node.agent_id, node, [item for item in supports if item is not None])
    node.quality_status = result.quality_status
    node.quality_scores = result.scores
    service.store.write_model_trace(trace)
    service.store.upsert_node(node)
    return dump_model(node)


try:
    from arq.connections import RedisSettings

    class WorkerSettings:
        functions = [build_summaries_job, refresh_job, verify_job]
        redis_settings = RedisSettings()

except ImportError:
    WorkerSettings = None
