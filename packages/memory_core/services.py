from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from packages.memory_core.model_components import ModelBackedSummarizer, ModelBackedVerifier, build_model_client
from packages.memory_core.settings import Settings
from packages.memory_core.storage import Database, MemoryStore
from packages.memory_core.utils import (
    extract_entities,
    jaccard_similarity,
    normalize_importance,
    pseudo_embedding,
    recency_score,
    relevance_score,
    source_hash,
    token_count,
    unique_topics,
)
from packages.schemas.models import (
    AgentTreeResponse,
    BuildSummariesRequest,
    CreatedBy,
    EvalRunResult,
    MemoryLevel,
    MemoryNode,
    NodeProvenance,
    NodeType,
    QualityStatus,
    QueryMode,
    RefreshRequest,
    RetrievalDiagnostics,
    RetrievalTrace,
    RetrievalTraceEntry,
    RetrieveResponse,
    RetrievedNode,
    RetrievalMetadata,
    TimelineResponse,
    dump_model,
)


@dataclass
class CandidateScore:
    node: MemoryNode
    score: float
    relevance: float
    recency: float


class RefreshPolicy:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def mark_stale(self, request: RefreshRequest) -> list[MemoryNode]:
        parents = self.store.parent_nodes(request.changed_node_ids)
        stale_ids = [node.node_id for node in parents]
        return self.store.mark_stale(stale_ids)


class FlatRetriever:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        token_budget: int,
        limit: int = 8,
    ) -> list[CandidateScore]:
        nodes = self.store.list_nodes(agent_id=agent_id, level=MemoryLevel.L0)
        candidates: list[CandidateScore] = []
        for node in nodes:
            rel = relevance_score(query, node.text)
            rec = recency_score(query_time, node.timestamp_end)
            imp = normalize_importance(node.importance_score)
            score = statistics.fmean([rel, rec, imp])
            candidates.append(CandidateScore(node=node, score=score, relevance=rel, recency=rec))
        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        picked: list[CandidateScore] = []
        consumed = 0
        for item in ranked:
            if len(picked) >= limit:
                break
            if consumed + item.node.token_count > token_budget:
                continue
            consumed += item.node.token_count
            self.store.mark_accessed(item.node.node_id, item.relevance, item.recency, query_time)
            picked.append(item)
        return picked


class TreeBuilder:
    def __init__(
        self,
        store: MemoryStore,
        summarizer: ModelBackedSummarizer,
        verifier: ModelBackedVerifier,
        settings: Settings,
    ) -> None:
        self.store = store
        self.summarizer = summarizer
        self.verifier = verifier
        self.settings = settings

    def build_level(self, request: BuildSummariesRequest) -> list[MemoryNode]:
        if request.source_level != MemoryLevel.L0 or request.target_level != MemoryLevel.L1:
            raise ValueError("The MVP only supports L0 to L1 summary construction.")
        nodes = self.store.list_nodes(agent_id=request.agent_id, level=request.source_level)
        clusters = self._cluster_nodes(nodes)
        built: list[MemoryNode] = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            support_hash = source_hash([item.node_id for item in cluster] + [item.text for item in cluster])
            existing = self.store.existing_summary(
                agent_id=request.agent_id,
                target_level=request.target_level,
                support_hash=support_hash,
            )
            if existing is not None:
                built.append(existing)
                continue
            summary_result, summary_trace = self.summarizer.generate(request.agent_id, cluster)
            summary_node = MemoryNode(
                node_id=str(uuid.uuid4()),
                agent_id=request.agent_id,
                level=request.target_level,
                node_type=NodeType.SUMMARY,
                text=summary_result.text,
                timestamp_start=cluster[0].timestamp_start,
                timestamp_end=cluster[-1].timestamp_end,
                parent_ids=[],
                child_ids=[node.node_id for node in cluster],
                support_ids=[node.node_id for node in cluster],
                embedding=pseudo_embedding(summary_result.text),
                importance_score=max(node.importance_score for node in cluster),
                retrieval_metadata=RetrievalMetadata(),
                entities=summary_result.entities or extract_entities(summary_result.text),
                topics=summary_result.topics or unique_topics(summary_result.text),
                version=self.store.next_version(request.agent_id, request.target_level, support_hash),
                stale_flag=False,
                summary_policy_id="rolling-window-v1",
                quality_status=QualityStatus.PENDING,
                quality_scores={},
                token_count=token_count(summary_result.text),
                source_hash=support_hash,
                created_by=CreatedBy.SUMMARIZER,
                prompt_version=summary_result.prompt_version,
                model_version=summary_result.model_version,
            )
            summary_trace.node_id = summary_node.node_id
            self.store.write_model_trace(summary_trace)
            verification_result, verification_trace = self.verifier.verify(request.agent_id, summary_node, cluster)
            summary_node.quality_status = verification_result.quality_status
            summary_node.quality_scores = verification_result.scores
            verification_trace.node_id = summary_node.node_id
            self.store.write_model_trace(verification_trace)
            if summary_node.quality_status == QualityStatus.CONTRADICTED:
                continue
            self.store.upsert_node(summary_node)
            for child in cluster:
                if summary_node.node_id not in child.parent_ids:
                    child.parent_ids.append(summary_node.node_id)
                    self.store.upsert_node(child)
            built.append(summary_node)
        return built

    def _cluster_nodes(self, nodes: list[MemoryNode]) -> list[list[MemoryNode]]:
        if not nodes:
            return []
        clusters: list[list[MemoryNode]] = []
        current: list[MemoryNode] = [nodes[0]]
        for node in nodes[1:]:
            prev = current[-1]
            within_window = node.timestamp_start - prev.timestamp_end <= timedelta(hours=self.settings.time_window_hours)
            semantically_related = (
                jaccard_similarity(node.text, " ".join(item.text for item in current))
                >= self.settings.cluster_similarity_threshold
            )
            shared_topic = bool(set(node.topics) & {topic for item in current for topic in item.topics})
            shared_entity = bool(set(node.entities) & {entity for item in current for entity in item.entities})
            important_context = max(item.importance_score for item in current + [node]) >= 0.8 and node.importance_score >= 0.6
            if within_window and (semantically_related or shared_topic or shared_entity or important_context):
                current.append(node)
            else:
                clusters.append(current)
                current = [node]
        clusters.append(current)
        return clusters


class HierarchicalRetriever:
    def __init__(self, store: MemoryStore, flat_retriever: FlatRetriever, settings: Settings) -> None:
        self.store = store
        self.flat_retriever = flat_retriever
        self.settings = settings

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        branch_limit: int,
    ) -> tuple[list[CandidateScore], int, list[RetrievalTraceEntry]]:
        summaries = self.store.list_nodes(agent_id=agent_id, level=MemoryLevel.L1)
        summary_scores: list[CandidateScore] = []
        trace_entries: list[RetrievalTraceEntry] = []
        for node in summaries:
            rel = relevance_score(query, node.text)
            rec = recency_score(query_time, node.timestamp_end)
            score = statistics.fmean([rel * 1.4, rec * 0.7, normalize_importance(node.importance_score)])
            summary_scores.append(CandidateScore(node=node, score=score, relevance=rel, recency=rec))
        ranked_summaries = sorted(summary_scores, key=lambda item: item.score, reverse=True)[:branch_limit]
        picked: list[CandidateScore] = []
        consumed = 0
        max_depth = 1 if ranked_summaries else 0
        for summary in ranked_summaries:
            if consumed + summary.node.token_count <= token_budget:
                picked.append(summary)
                consumed += summary.node.token_count
                self.store.mark_accessed(summary.node.node_id, summary.relevance, summary.recency, query_time)
                trace_entries.append(
                    RetrievalTraceEntry(
                        node_id=summary.node.node_id,
                        level=summary.node.level,
                        node_type=summary.node.node_type,
                        score=summary.score,
                        relevance_score=summary.relevance,
                        recency_score=summary.recency,
                        importance_score=summary.node.importance_score,
                        branch_root_id=summary.node.node_id,
                        selected_as="summary",
                        selection_reason="Selected as top branch candidate.",
                    )
                )
            descend = mode == QueryMode.DRILL_DOWN
            if mode == QueryMode.BALANCED and summary.relevance < 0.55:
                descend = True
            if mode == QueryMode.SUMMARY_ONLY or not descend:
                continue
            max_depth = max(max_depth, 2)
            children = [self.store.get_node(child_id) for child_id in summary.node.child_ids]
            child_scores: list[CandidateScore] = []
            for child in children:
                if child is None:
                    continue
                rel = relevance_score(query, child.text)
                rec = recency_score(query_time, child.timestamp_end)
                score = statistics.fmean([rel * 1.2, rec * 0.4, normalize_importance(child.importance_score)])
                child_scores.append(CandidateScore(node=child, score=score, relevance=rel, recency=rec))
            for child in sorted(child_scores, key=lambda item: item.score, reverse=True):
                if consumed + child.node.token_count > token_budget:
                    continue
                consumed += child.node.token_count
                self.store.mark_accessed(child.node.node_id, child.relevance, child.recency, query_time)
                picked.append(child)
                trace_entries.append(
                    RetrievalTraceEntry(
                        node_id=child.node.node_id,
                        level=child.node.level,
                        node_type=child.node.node_type,
                        score=child.score,
                        relevance_score=child.relevance,
                        recency_score=child.recency,
                        importance_score=child.node.importance_score,
                        branch_root_id=summary.node.node_id,
                        selected_as="supporting_leaf",
                        selection_reason="Descended into branch for higher precision.",
                    )
                )
                if mode != QueryMode.DRILL_DOWN:
                    break
        if not picked:
            fallback = self.flat_retriever.retrieve(agent_id, query, query_time, token_budget, limit=branch_limit)
            fallback_entries = [
                RetrievalTraceEntry(
                    node_id=item.node.node_id,
                    level=item.node.level,
                    node_type=item.node.node_type,
                    score=item.score,
                    relevance_score=item.relevance,
                    recency_score=item.recency,
                    importance_score=item.node.importance_score,
                    branch_root_id=None,
                    selected_as="flat_fallback",
                    selection_reason="No summary branch survived ranking, so flat retrieval was used.",
                )
                for item in fallback
            ]
            return fallback, 1, fallback_entries
        ranked = sorted(picked, key=lambda item: item.score, reverse=True)
        return ranked, max_depth, trace_entries


class ContextPacker:
    def pack(self, query: str, candidates: list[CandidateScore], token_budget: int) -> str:
        lines = [f"Query: {query}", "Context:"]
        consumed = token_count(query)
        for candidate in candidates:
            snippet = f"[{candidate.node.level.value}/{candidate.node.node_type.value}] {candidate.node.text}"
            snippet_tokens = token_count(snippet)
            if consumed + snippet_tokens > token_budget:
                continue
            lines.append(snippet)
            consumed += snippet_tokens
        return "\n".join(lines)


def build_retrieval_diagnostics(
    candidates: list[CandidateScore],
    trace_entries: list[RetrievalTraceEntry],
    packed_context: str,
) -> RetrievalDiagnostics:
    retrieved_token_count = sum(item.node.token_count for item in candidates)
    summary_node_count = sum(1 for item in candidates if item.node.level != MemoryLevel.L0)
    supporting_leaf_count = sum(1 for entry in trace_entries if entry.selected_as == "supporting_leaf")
    branch_count = len({entry.branch_root_id for entry in trace_entries if entry.branch_root_id})
    scores = [item.score for item in candidates]
    return RetrievalDiagnostics(
        retrieved_node_count=len(candidates),
        summary_node_count=summary_node_count,
        leaf_node_count=sum(1 for item in candidates if item.node.level == MemoryLevel.L0),
        supporting_leaf_count=supporting_leaf_count,
        retrieved_token_count=retrieved_token_count,
        packed_token_count=token_count(packed_context),
        branch_count=branch_count,
        avg_score=statistics.fmean(scores) if scores else 0.0,
        max_score=max(scores, default=0.0),
        fallback_used=any(entry.selected_as == "flat_fallback" for entry in trace_entries),
    )


class AgentLoopAdapter:
    def __init__(self, services: "MemoryService") -> None:
        self.services = services

    def observe(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.5) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.EPISODE)

    def reflect(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.7) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.REFLECTION)

    def plan(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.8) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.PLAN)


class MemoryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.database_url)
        self.store = MemoryStore(self.db, settings.prompt_version, settings.model_version)
        if settings.auto_create_schema:
            self.store.ensure_schema()
        model_client, provider = build_model_client(settings)
        self.summarizer = ModelBackedSummarizer(model_client, provider, settings)
        self.verifier = ModelBackedVerifier(model_client, provider, settings)
        self.refresh_policy = RefreshPolicy(self.store)
        self.flat_retriever = FlatRetriever(self.store)
        self.tree_builder = TreeBuilder(self.store, self.summarizer, self.verifier, settings)
        self.hierarchical_retriever = HierarchicalRetriever(self.store, self.flat_retriever, settings)
        self.context_packer = ContextPacker()
        self.agent_loop = AgentLoopAdapter(self)

    def build_summaries(self, request: BuildSummariesRequest) -> list[MemoryNode]:
        return self.tree_builder.build_level(request)

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        branch_limit: int,
    ) -> RetrieveResponse:
        retrieved, depth, trace_entries = self.hierarchical_retriever.retrieve(
            agent_id=agent_id,
            query=query,
            query_time=query_time,
            mode=mode,
            token_budget=token_budget,
            branch_limit=branch_limit,
        )
        packed = self.context_packer.pack(query, retrieved, token_budget)
        diagnostics = build_retrieval_diagnostics(retrieved, trace_entries, packed)
        trace = RetrievalTrace(
            trace_id=str(uuid.uuid4()),
            agent_id=agent_id,
            query=query,
            mode=mode,
            token_budget=token_budget,
            retrieval_depth=depth,
            created_at=datetime.utcnow(),
            entries=trace_entries,
            diagnostics=diagnostics,
        )
        self.store.write_retrieval_trace(trace)
        return RetrieveResponse(
            query=query,
            mode=mode,
            token_budget=token_budget,
            retrieved_nodes=[
                RetrievedNode(
                    node=item.node,
                    score=item.score,
                    branch_root_id=item.node.parent_ids[0] if item.node.parent_ids else None,
                    relevance_score=item.relevance,
                    recency_score=item.recency,
                    importance_score=item.node.importance_score,
                    selected_as=next((entry.selected_as for entry in trace_entries if entry.node_id == item.node.node_id), None),
                    selection_reason=next(
                        (entry.selection_reason for entry in trace_entries if entry.node_id == item.node.node_id),
                        None,
                    ),
                )
                for item in retrieved
            ],
            packed_context=packed,
            retrieval_depth=depth,
            trace_id=trace.trace_id,
            trace_entries=trace_entries,
            diagnostics=diagnostics,
        )

    def retrieve_flat(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        token_budget: int,
        branch_limit: int,
    ) -> RetrieveResponse:
        retrieved = self.flat_retriever.retrieve(agent_id, query, query_time, token_budget, limit=branch_limit)
        packed = self.context_packer.pack(query, retrieved, token_budget)
        trace_entries = [
            RetrievalTraceEntry(
                node_id=item.node.node_id,
                level=item.node.level,
                node_type=item.node.node_type,
                score=item.score,
                relevance_score=item.relevance,
                recency_score=item.recency,
                importance_score=item.node.importance_score,
                branch_root_id=None,
                selected_as="flat_memory",
                selection_reason="Baseline flat retrieval.",
            )
            for item in retrieved
        ]
        diagnostics = build_retrieval_diagnostics(retrieved, trace_entries, packed)
        trace = RetrievalTrace(
            trace_id=str(uuid.uuid4()),
            agent_id=agent_id,
            query=query,
            mode=QueryMode.BALANCED,
            token_budget=token_budget,
            retrieval_depth=1 if retrieved else 0,
            created_at=datetime.utcnow(),
            entries=trace_entries,
            diagnostics=diagnostics,
        )
        self.store.write_retrieval_trace(trace)
        return RetrieveResponse(
            query=query,
            mode=QueryMode.BALANCED,
            token_budget=token_budget,
            retrieved_nodes=[
                RetrievedNode(
                    node=item.node,
                    score=item.score,
                    relevance_score=item.relevance,
                    recency_score=item.recency,
                    importance_score=item.node.importance_score,
                    selected_as="flat_memory",
                    selection_reason="Baseline flat retrieval.",
                )
                for item in retrieved
            ],
            packed_context=packed,
            retrieval_depth=1 if retrieved else 0,
            trace_id=trace.trace_id,
            trace_entries=trace_entries,
            diagnostics=diagnostics,
        )

    def refresh(self, request: RefreshRequest) -> list[MemoryNode]:
        return self.refresh_policy.mark_stale(request)

    def node_provenance(self, node_id: str) -> NodeProvenance:
        root = self.store.get_node(node_id)
        if root is None:
            raise KeyError(node_id)
        ancestors, descendants, supports = self.store.node_provenance(node_id)
        return NodeProvenance(root=root, ancestors=ancestors, descendants=descendants, supports=supports)

    def timeline(self, agent_id: str) -> TimelineResponse:
        return TimelineResponse(agent_id=agent_id, nodes=self.store.list_nodes(agent_id=agent_id, include_stale=True))

    def agent_tree(self, agent_id: str) -> AgentTreeResponse:
        return self.store.agent_tree(agent_id)

    def retrieval_traces(self, agent_id: str | None = None, limit: int = 20) -> list[RetrievalTrace]:
        return self.store.list_retrieval_traces(agent_id=agent_id, limit=limit)

    def model_traces(self, agent_id: str | None = None, limit: int = 20):
        return self.store.list_model_traces(agent_id=agent_id, limit=limit)

    def eval_runs(self) -> list[dict]:
        return self.store.list_eval_runs()

    def record_eval(self, result: EvalRunResult) -> None:
        self.store.write_eval_run(result.scenario_name, json.dumps(dump_model(result), default=str))
