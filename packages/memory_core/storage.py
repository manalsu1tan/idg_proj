from __future__ import annotations

"""Persistence layer and ORM models
Reads writes nodes traces and eval records"""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from packages.memory_core.utils import (
    extract_entities,
    normalize_datetime,
    pseudo_embedding,
    source_hash,
    token_count,
    unique_topics,
)
from packages.schemas.models import (
    AgentTreeResponse,
    CreatedBy,
    MemoryLevel,
    MemoryNode,
    ModelProvider,
    ModelTrace,
    NodeType,
    QualityStatus,
    RetrievalMetadata,
    RetrievalTrace,
    RetrievalTraceEntry,
    TreeNode,
    dump_model,
    dump_model_json,
)

try:
    from pgvector.sqlalchemy import Vector

    PGVECTOR_AVAILABLE = True
except ImportError:
    Vector = None
    PGVECTOR_AVAILABLE = False


Base = declarative_base()


def embedding_column_type():
    """Return db type for embedding storage"""
    if PGVECTOR_AVAILABLE:
        return Vector(12)
    return Text


class NodeRecord(Base):
    __tablename__ = "memory_nodes"

    node_id = Column(String(64), primary_key=True)
    agent_id = Column(String(64), index=True)
    level = Column(String(8), index=True)
    node_type = Column(String(32), index=True)
    text = Column(Text)
    timestamp_start = Column(DateTime(timezone=False), index=True)
    timestamp_end = Column(DateTime(timezone=False), index=True)
    parent_ids = Column(Text, default="[]")
    child_ids = Column(Text, default="[]")
    support_ids = Column(Text, default="[]")
    embedding = Column(embedding_column_type(), nullable=True)
    importance_score = Column(Float, default=0.0)
    recency_score = Column(Float, default=0.0)
    relevance_score = Column(Float, default=0.0)
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime(timezone=False), nullable=True)
    entities = Column(Text, default="[]")
    topics = Column(Text, default="[]")
    commitments = Column(Text, default="[]")
    revisions = Column(Text, default="[]")
    preferences = Column(Text, default="[]")
    relationship_guidance = Column(Text, default="[]")
    self_model_updates = Column(Text, default="[]")
    version = Column(Integer, default=1)
    stale_flag = Column(Boolean, default=False)
    summary_policy_id = Column(String(64), nullable=True)
    quality_status = Column(String(32), default=QualityStatus.PENDING.value)
    quality_scores = Column(Text, default="{}")
    token_count = Column(Integer, default=0)
    source_hash = Column(String(128), default="")
    created_by = Column(String(32), default=CreatedBy.SYSTEM.value)
    prompt_version = Column(String(64), nullable=True)
    model_version = Column(String(64), nullable=True)


class EdgeRecord(Base):
    __tablename__ = "memory_edges"

    edge_id = Column(String(64), primary_key=True)
    parent_id = Column(String(64), index=True)
    child_id = Column(String(64), index=True)
    edge_type = Column(String(32), index=True)


class EvalRunRecord(Base):
    __tablename__ = "eval_runs"

    run_id = Column(String(64), primary_key=True)
    scenario_name = Column(String(128), index=True)
    created_at = Column(DateTime(timezone=False))
    payload = Column(Text)


class RetrievalTraceRecord(Base):
    __tablename__ = "retrieval_traces"

    trace_id = Column(String(64), primary_key=True)
    agent_id = Column(String(64), index=True)
    query = Column(Text)
    mode = Column(String(32), index=True)
    token_budget = Column(Integer)
    retrieval_depth = Column(Integer)
    created_at = Column(DateTime(timezone=False), index=True)
    payload = Column(Text)


class ModelTraceRecord(Base):
    __tablename__ = "model_traces"

    trace_id = Column(String(64), primary_key=True)
    node_id = Column(String(64), index=True, nullable=True)
    agent_id = Column(String(64), index=True)
    component = Column(String(32), index=True)
    provider = Column(String(32), index=True)
    model_name = Column(String(128))
    prompt_version = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=False), index=True)
    request_payload = Column(Text)
    response_payload = Column(Text)


class Database:
    """Database wrapper for engine and sessions
    Owns transaction lifecycle and shared session factory setup"""

    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, future=True)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def verify_connection(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class MemoryStore:
    """Persistence facade for memory tree data
    Reads writes nodes traces lineage and eval artifacts"""

    def __init__(self, db: Database, prompt_version: str, model_version: str) -> None:
        self.db = db
        self.prompt_version = prompt_version
        self.model_version = model_version

    def ensure_schema(self) -> None:
        self.db.create_all()

    def write_l0(
        self,
        agent_id: str,
        text: str,
        timestamp: datetime,
        importance_score: float,
        node_type: NodeType,
        entities: list[str] | None = None,
        topics: list[str] | None = None,
    ) -> MemoryNode:
        timestamp = normalize_datetime(timestamp)
        node = MemoryNode(
            node_id=str(uuid.uuid4()),
            agent_id=agent_id,
            level=MemoryLevel.L0,
            node_type=node_type,
            text=text,
            timestamp_start=timestamp,
            timestamp_end=timestamp,
            parent_ids=[],
            child_ids=[],
            support_ids=[],
            embedding=pseudo_embedding(text),
            importance_score=importance_score,
            entities=entities or extract_entities(text),
            topics=topics or unique_topics(text),
            commitments=[],
            revisions=[],
            preferences=[],
            relationship_guidance=[],
            self_model_updates=[],
            version=1,
            stale_flag=False,
            summary_policy_id=None,
            quality_status=QualityStatus.VERIFIED if node_type != NodeType.SUMMARY else QualityStatus.PENDING,
            quality_scores={},
            token_count=token_count(text),
            source_hash=source_hash([text, timestamp.isoformat()]),
            created_by=CreatedBy.AGENT,
            prompt_version=self.prompt_version,
            model_version=self.model_version,
        )
        self.upsert_node(node)
        return node

    def upsert_node(self, node: MemoryNode) -> MemoryNode:
        with self.db.session() as session:
            record = session.get(NodeRecord, node.node_id) or NodeRecord(node_id=node.node_id)
            record.agent_id = node.agent_id
            record.level = node.level.value
            record.node_type = node.node_type.value
            record.text = node.text
            record.timestamp_start = node.timestamp_start
            record.timestamp_end = node.timestamp_end
            record.parent_ids = json.dumps(node.parent_ids)
            record.child_ids = json.dumps(node.child_ids)
            record.support_ids = json.dumps(node.support_ids)
            if node.embedding is None:
                record.embedding = None
            elif PGVECTOR_AVAILABLE:
                record.embedding = node.embedding
            else:
                record.embedding = json.dumps(node.embedding)
            record.importance_score = node.importance_score
            record.recency_score = node.retrieval_metadata.recency_score
            record.relevance_score = node.retrieval_metadata.relevance_score
            record.access_count = node.retrieval_metadata.access_count
            record.last_accessed_at = node.retrieval_metadata.last_accessed_at
            record.entities = json.dumps(node.entities)
            record.topics = json.dumps(node.topics)
            record.commitments = json.dumps(node.commitments)
            record.revisions = json.dumps(node.revisions)
            record.preferences = json.dumps(node.preferences)
            record.relationship_guidance = json.dumps(node.relationship_guidance)
            record.self_model_updates = json.dumps(node.self_model_updates)
            record.version = node.version
            record.stale_flag = node.stale_flag
            record.summary_policy_id = node.summary_policy_id
            record.quality_status = node.quality_status.value
            record.quality_scores = json.dumps(node.quality_scores)
            record.token_count = node.token_count
            record.source_hash = node.source_hash
            record.created_by = node.created_by.value
            record.prompt_version = node.prompt_version
            record.model_version = node.model_version
            session.add(record)
            session.query(EdgeRecord).filter(EdgeRecord.parent_id == node.node_id).delete()
            for child_id in node.child_ids:
                session.add(
                    EdgeRecord(
                        edge_id=str(uuid.uuid4()),
                        parent_id=node.node_id,
                        child_id=child_id,
                        edge_type="child",
                    )
                )
            for support_id in node.support_ids:
                session.add(
                    EdgeRecord(
                        edge_id=str(uuid.uuid4()),
                        parent_id=node.node_id,
                        child_id=support_id,
                        edge_type="support",
                    )
                )
        return node

    def list_nodes(
        self,
        agent_id: str,
        level: MemoryLevel | None = None,
        include_stale: bool = False,
    ) -> list[MemoryNode]:
        with self.db.session() as session:
            stmt = select(NodeRecord).where(NodeRecord.agent_id == agent_id)
            if level is not None:
                stmt = stmt.where(NodeRecord.level == level.value)
            if not include_stale:
                stmt = stmt.where(NodeRecord.stale_flag.is_(False))
            stmt = stmt.order_by(NodeRecord.timestamp_start.asc())
            return [self._to_node(record) for record in session.execute(stmt).scalars().all()]

    def child_nodes(self, node_id: str, edge_type: str = "child") -> list[MemoryNode]:
        with self.db.session() as session:
            child_ids = [
                item
                for item in session.execute(
                    select(EdgeRecord.child_id).where(
                        EdgeRecord.parent_id == node_id,
                        EdgeRecord.edge_type == edge_type,
                    )
                ).scalars().all()
            ]
        return [node for item in child_ids if (node := self.get_node(item)) is not None]

    def get_node(self, node_id: str) -> MemoryNode | None:
        with self.db.session() as session:
            record = session.get(NodeRecord, node_id)
            return self._to_node(record) if record else None

    def mark_accessed(self, node_id: str, relevance: float, recency: float, accessed_at: datetime) -> None:
        accessed_at = normalize_datetime(accessed_at)
        with self.db.session() as session:
            record = session.get(NodeRecord, node_id)
            if record is None:
                return
            record.access_count += 1
            record.last_accessed_at = accessed_at
            record.relevance_score = relevance
            record.recency_score = recency
            session.add(record)

    def mark_stale(self, node_ids: list[str]) -> list[MemoryNode]:
        updated: list[MemoryNode] = []
        with self.db.session() as session:
            for node_id in node_ids:
                record = session.get(NodeRecord, node_id)
                if record is None:
                    continue
                record.stale_flag = True
                session.add(record)
                updated.append(self._to_node(record))
        return updated

    def next_version(self, agent_id: str, target_level: MemoryLevel, support_hash: str) -> int:
        nodes = self.list_nodes(agent_id=agent_id, level=target_level, include_stale=True)
        versions = [node.version for node in nodes if node.source_hash == support_hash]
        return max(versions, default=0) + 1

    def existing_summary(self, agent_id: str, target_level: MemoryLevel, support_hash: str) -> MemoryNode | None:
        summaries = self.list_nodes(agent_id=agent_id, level=target_level, include_stale=False)
        for node in summaries:
            if node.source_hash == support_hash:
                return node
        return None

    def parent_nodes(self, child_ids: list[str]) -> list[MemoryNode]:
        if not child_ids:
            return []
        with self.db.session() as session:
            stmt = select(EdgeRecord.parent_id).where(
                EdgeRecord.child_id.in_(child_ids),
                EdgeRecord.edge_type == "child",
            )
            parent_ids = [item for item in session.execute(stmt).scalars().all()]
        return [node for node_id in parent_ids if (node := self.get_node(node_id)) is not None]

    def node_provenance(self, node_id: str) -> tuple[list[MemoryNode], list[MemoryNode], list[MemoryNode]]:
        with self.db.session() as session:
            descendant_ids = [
                item
                for item in session.execute(
                    select(EdgeRecord.child_id).where(
                        EdgeRecord.parent_id == node_id,
                        EdgeRecord.edge_type == "child",
                    )
                ).scalars().all()
            ]
            support_ids = [
                item
                for item in session.execute(
                    select(EdgeRecord.child_id).where(
                        EdgeRecord.parent_id == node_id,
                        EdgeRecord.edge_type == "support",
                    )
                ).scalars().all()
            ]
        ancestors = self.parent_nodes([node_id])
        descendants = [node for item in descendant_ids if (node := self.get_node(item)) is not None]
        supports = [node for item in support_ids if (node := self.get_node(item)) is not None]
        return ancestors, descendants, supports

    def write_eval_run(self, scenario_name: str, payload: str) -> None:
        with self.db.session() as session:
            session.add(
                EvalRunRecord(
                    run_id=str(uuid.uuid4()),
                    scenario_name=scenario_name,
                    created_at=datetime.utcnow(),
                    payload=payload,
                )
            )

    def list_eval_runs(self) -> list[dict]:
        with self.db.session() as session:
            stmt = select(EvalRunRecord).order_by(EvalRunRecord.created_at.desc())
            return [json.loads(record.payload) for record in session.execute(stmt).scalars().all()]

    def delete_agent_data(self, agent_id: str) -> None:
        with self.db.session() as session:
            node_ids = [
                item
                for item in session.execute(
                    select(NodeRecord.node_id).where(NodeRecord.agent_id == agent_id)
                ).scalars().all()
            ]
            if node_ids:
                session.query(EdgeRecord).filter(
                    (EdgeRecord.parent_id.in_(node_ids)) | (EdgeRecord.child_id.in_(node_ids))
                ).delete(synchronize_session=False)
                session.query(NodeRecord).filter(NodeRecord.node_id.in_(node_ids)).delete(synchronize_session=False)
            session.query(RetrievalTraceRecord).filter(RetrievalTraceRecord.agent_id == agent_id).delete(synchronize_session=False)
            session.query(ModelTraceRecord).filter(ModelTraceRecord.agent_id == agent_id).delete(synchronize_session=False)

    def write_retrieval_trace(self, trace: RetrievalTrace) -> None:
        with self.db.session() as session:
            session.add(
                RetrievalTraceRecord(
                    trace_id=trace.trace_id,
                    agent_id=trace.agent_id,
                    query=trace.query,
                    mode=trace.mode.value,
                    token_budget=trace.token_budget,
                    retrieval_depth=trace.retrieval_depth,
                    created_at=trace.created_at,
                    payload=json.dumps(
                        {
                            "trace_id": trace.trace_id,
                            "agent_id": trace.agent_id,
                            "query": trace.query,
                            "mode": trace.mode.value,
                            "token_budget": trace.token_budget,
                            "retrieval_depth": trace.retrieval_depth,
                            "created_at": trace.created_at.isoformat(),
                            "entries": [dump_model_json(entry) for entry in trace.entries],
                            "diagnostics": dump_model_json(trace.diagnostics),
                        }
                    ),
                )
            )

    def list_retrieval_traces(self, agent_id: str | None = None, limit: int = 20) -> list[RetrievalTrace]:
        with self.db.session() as session:
            stmt = select(RetrievalTraceRecord).order_by(RetrievalTraceRecord.created_at.desc())
            if agent_id:
                stmt = stmt.where(RetrievalTraceRecord.agent_id == agent_id)
            stmt = stmt.limit(limit)
            records = session.execute(stmt).scalars().all()
        traces: list[RetrievalTrace] = []
        for record in records:
            payload = json.loads(record.payload)
            traces.append(
                RetrievalTrace(
                    trace_id=payload["trace_id"],
                    agent_id=payload["agent_id"],
                    query=payload["query"],
                    mode=payload["mode"],
                    token_budget=payload["token_budget"],
                    retrieval_depth=payload["retrieval_depth"],
                    created_at=payload["created_at"],
                    entries=[RetrievalTraceEntry(**entry) for entry in payload.get("entries", [])],
                    diagnostics=payload.get("diagnostics", {}),
                )
            )
        return traces

    def write_model_trace(self, trace: ModelTrace) -> None:
        with self.db.session() as session:
            session.add(
                ModelTraceRecord(
                    trace_id=trace.trace_id,
                    node_id=trace.node_id,
                    agent_id=trace.agent_id,
                    component=trace.component,
                    provider=trace.provider.value,
                    model_name=trace.model_name,
                    prompt_version=trace.prompt_version,
                    created_at=trace.created_at,
                    request_payload=json.dumps(trace.request_payload, default=str),
                    response_payload=json.dumps(trace.response_payload, default=str),
                )
            )

    def list_model_traces(self, agent_id: str | None = None, limit: int = 20) -> list[ModelTrace]:
        with self.db.session() as session:
            stmt = select(ModelTraceRecord).order_by(ModelTraceRecord.created_at.desc())
            if agent_id:
                stmt = stmt.where(ModelTraceRecord.agent_id == agent_id)
            stmt = stmt.limit(limit)
            records = session.execute(stmt).scalars().all()
        traces: list[ModelTrace] = []
        for record in records:
            traces.append(
                ModelTrace(
                    trace_id=record.trace_id,
                    node_id=record.node_id,
                    agent_id=record.agent_id,
                    component=record.component,
                    provider=ModelProvider(record.provider),
                    model_name=record.model_name,
                    prompt_version=record.prompt_version,
                    created_at=record.created_at,
                    request_payload=json.loads(record.request_payload),
                    response_payload=json.loads(record.response_payload),
                )
            )
        return traces

    def agent_tree(self, agent_id: str) -> AgentTreeResponse:
        nodes = self.list_nodes(agent_id=agent_id, include_stale=True)
        by_id = {node.node_id: TreeNode(node=node, children=[]) for node in nodes}
        roots: list[TreeNode] = []
        for tree_node in by_id.values():
            if tree_node.node.parent_ids:
                parent_id = tree_node.node.parent_ids[0]
                parent = by_id.get(parent_id)
                if parent is not None:
                    parent.children.append(tree_node)
                    continue
            roots.append(tree_node)
        roots.sort(key=lambda item: item.node.timestamp_start)
        return AgentTreeResponse(agent_id=agent_id, roots=roots)

    def _to_node(self, record: NodeRecord) -> MemoryNode:
        return MemoryNode(
            node_id=record.node_id,
            agent_id=record.agent_id,
            level=MemoryLevel(record.level),
            node_type=NodeType(record.node_type),
            text=record.text,
            timestamp_start=record.timestamp_start,
            timestamp_end=record.timestamp_end,
            parent_ids=json.loads(record.parent_ids),
            child_ids=json.loads(record.child_ids),
            support_ids=json.loads(record.support_ids),
            embedding=(
                list(record.embedding)
                if PGVECTOR_AVAILABLE and record.embedding is not None
                else json.loads(record.embedding)
                if record.embedding
                else None
            ),
            importance_score=record.importance_score,
            retrieval_metadata=RetrievalMetadata(
                recency_score=record.recency_score,
                relevance_score=record.relevance_score,
                access_count=record.access_count,
                last_accessed_at=record.last_accessed_at,
            ),
            entities=json.loads(record.entities),
            topics=json.loads(record.topics),
            commitments=json.loads(record.commitments),
            revisions=json.loads(record.revisions),
            preferences=json.loads(record.preferences),
            relationship_guidance=json.loads(record.relationship_guidance),
            self_model_updates=json.loads(record.self_model_updates),
            version=record.version,
            stale_flag=record.stale_flag,
            summary_policy_id=record.summary_policy_id,
            quality_status=QualityStatus(record.quality_status),
            quality_scores=json.loads(record.quality_scores),
            token_count=record.token_count,
            source_hash=record.source_hash,
            created_by=CreatedBy(record.created_by),
            prompt_version=record.prompt_version,
            model_version=record.model_version,
        )
