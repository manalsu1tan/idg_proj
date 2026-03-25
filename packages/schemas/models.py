from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class NodeType(str, Enum):
    EPISODE = "episode"
    REFLECTION = "reflection"
    PLAN = "plan"
    SUMMARY = "summary"


class QualityStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class CreatedBy(str, Enum):
    AGENT = "agent"
    SUMMARIZER = "summarizer"
    VERIFIER = "verifier"
    SYSTEM = "system"


class QueryMode(str, Enum):
    BALANCED = "balanced"
    SUMMARY_ONLY = "summary_only"
    DRILL_DOWN = "drill_down"


class AblationMode(str, Enum):
    FLAT_BASELINE = "flat_baseline"
    HIERARCHY_SUMMARY_ONLY = "hierarchy_summary_only"
    HIERARCHY_BALANCED = "hierarchy_balanced"
    HIERARCHY_DRILL_DOWN = "hierarchy_drill_down"
    HIERARCHY_TOP_LEAF_ONLY = "hierarchy_top_leaf_only"


class ModelProvider(str, Enum):
    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"


class RetrievalMetadata(BaseModel):
    recency_score: float = 0.0
    relevance_score: float = 0.0
    access_count: int = 0
    last_accessed_at: datetime | None = None


class StructuredSummary(BaseModel):
    commitments: list[str] = Field(default_factory=list)
    revisions: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    relationship_guidance: list[str] = Field(default_factory=list)
    self_model_updates: list[str] = Field(default_factory=list)


class MemoryNode(BaseModel):
    node_id: str
    agent_id: str
    level: MemoryLevel
    node_type: NodeType
    text: str
    timestamp_start: datetime
    timestamp_end: datetime
    parent_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)
    support_ids: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None
    importance_score: float = 0.0
    retrieval_metadata: RetrievalMetadata = Field(default_factory=RetrievalMetadata)
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    revisions: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    relationship_guidance: list[str] = Field(default_factory=list)
    self_model_updates: list[str] = Field(default_factory=list)
    version: int = 1
    stale_flag: bool = False
    summary_policy_id: str | None = None
    quality_status: QualityStatus = QualityStatus.PENDING
    quality_scores: dict[str, float] = Field(default_factory=dict)
    token_count: int = 0
    source_hash: str = ""
    created_by: CreatedBy = CreatedBy.SYSTEM
    prompt_version: str | None = None
    model_version: str | None = None


class MemoryEdge(BaseModel):
    parent_id: str
    child_id: str
    edge_type: str


class IngestMemoryRequest(BaseModel):
    agent_id: str
    text: str
    timestamp: datetime
    importance_score: float = 0.5
    node_type: NodeType = NodeType.EPISODE
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class RetrieveRequest(BaseModel):
    agent_id: str
    query: str
    query_time: datetime
    mode: QueryMode = QueryMode.BALANCED
    token_budget: int = 180
    branch_limit: int = 3


class RetrievedNode(BaseModel):
    node: MemoryNode
    score: float
    branch_root_id: str | None = None
    relevance_score: float | None = None
    recency_score: float | None = None
    importance_score: float | None = None
    selected_as: str | None = None
    selection_reason: str | None = None


class RetrievalTraceEntry(BaseModel):
    node_id: str
    level: MemoryLevel
    node_type: NodeType
    score: float
    relevance_score: float
    recency_score: float
    importance_score: float
    branch_root_id: str | None = None
    selected_as: str
    selection_reason: str


class RetrievalDiagnostics(BaseModel):
    retrieved_node_count: int = 0
    summary_node_count: int = 0
    leaf_node_count: int = 0
    supporting_leaf_count: int = 0
    retrieved_token_count: int = 0
    packed_token_count: int = 0
    branch_count: int = 0
    avg_score: float = 0.0
    max_score: float = 0.0
    fallback_used: bool = False


class RetrievalTrace(BaseModel):
    trace_id: str
    agent_id: str
    query: str
    mode: QueryMode
    token_budget: int
    retrieval_depth: int
    created_at: datetime
    entries: list[RetrievalTraceEntry] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics = Field(default_factory=RetrievalDiagnostics)


class RetrieveResponse(BaseModel):
    query: str
    mode: QueryMode
    token_budget: int
    retrieved_nodes: list[RetrievedNode]
    packed_context: str
    retrieval_depth: int
    trace_id: str | None = None
    trace_entries: list[RetrievalTraceEntry] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics = Field(default_factory=RetrievalDiagnostics)


class BuildSummariesRequest(BaseModel):
    agent_id: str
    source_level: MemoryLevel = MemoryLevel.L0
    target_level: MemoryLevel = MemoryLevel.L1
    query_time: datetime | None = None


class RefreshRequest(BaseModel):
    agent_id: str
    changed_node_ids: list[str]


class EvalRequest(BaseModel):
    agent_id: str = "benchmark-agent"


class EvalMetric(BaseModel):
    name: str
    value: float
    details: dict[str, Any] = Field(default_factory=dict)


class EvalRunResult(BaseModel):
    scenario_name: str
    baseline_metrics: list[EvalMetric]
    hierarchy_metrics: list[EvalMetric]
    notes: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class AblationModeResult(BaseModel):
    mode: AblationMode
    metrics: list[EvalMetric]
    notes: list[str] = Field(default_factory=list)


class AblationRunResult(BaseModel):
    scenario_name: str
    mode_results: list[AblationModeResult]
    best_mode: AblationMode
    notes: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class NodeProvenance(BaseModel):
    root: MemoryNode
    ancestors: list[MemoryNode] = Field(default_factory=list)
    descendants: list[MemoryNode] = Field(default_factory=list)
    supports: list[MemoryNode] = Field(default_factory=list)


class TimelineResponse(BaseModel):
    agent_id: str
    nodes: list[MemoryNode]


class TreeNode(BaseModel):
    node: MemoryNode
    children: list["TreeNode"] = Field(default_factory=list)


class AgentTreeResponse(BaseModel):
    agent_id: str
    roots: list[TreeNode]


class SummaryResult(BaseModel):
    text: str
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    revisions: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    relationship_guidance: list[str] = Field(default_factory=list)
    self_model_updates: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = Field(default_factory=list)
    prompt_version: str | None = None
    model_version: str | None = None
    raw_response: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    quality_status: QualityStatus
    unsupported_claims: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    prompt_version: str | None = None
    model_version: str | None = None
    raw_response: dict[str, Any] = Field(default_factory=dict)


class ModelTrace(BaseModel):
    trace_id: str
    node_id: str | None = None
    agent_id: str
    component: str
    provider: ModelProvider
    model_name: str
    prompt_version: str | None = None
    created_at: datetime
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)


def dump_model(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[no-any-return]
    return model.dict()  # type: ignore[no-any-return]


def dump_model_json(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")  # type: ignore[no-any-return]
    return json.loads(model.json())  # type: ignore[no-any-return]


TreeNode.update_forward_refs()
