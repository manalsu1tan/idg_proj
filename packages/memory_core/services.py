from __future__ import annotations

"""Service layer orchestration
Composes storage models retrieval and API facing ops"""

import json
import logging
import statistics
import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import OperationalError

from packages.memory_core.model_components import (
    ModelBackedAnswerVerifier,
    ModelBackedAnswerer,
    ModelBackedSummarizer,
    ModelBackedVerifier,
    build_model_client,
)
from packages.memory_core.social_state import build_social_state_digest
from packages.memory_core.retrieval.hierarchical import HierarchicalRetriever
from packages.memory_core.retrieval.diagnostics import (
    build_retrieval_diagnostics,
    make_retrieval_trace_entry,
)
from packages.memory_core.retrieval.pipeline_types import CandidateScore
from packages.memory_core.settings import Settings
from packages.memory_core.storage import Database, MemoryStore
from packages.memory_core.utils import (
    extract_entities,
    jaccard_similarity,
    normalize_datetime,
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
    BatchIngestMemoriesRequest,
    BatchIngestMemoriesResponse,
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
    RetrievalTrace,
    RetrievalTraceEntry,
    RetrieveResponse,
    RetrievedNode,
    RetrievalMetadata,
    SocialStateDigestResponse,
    TimelineResponse,
    dump_model,
)


logger = logging.getLogger(__name__)


class RefreshPolicy:
    """Marks affected summary parents as stale
    Used after source node edits to trigger rebuild flow"""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def mark_stale(self, request: RefreshRequest) -> list[MemoryNode]:
        """Mark ancestor summaries stale for changed leaves"""
        parents = self.store.parent_nodes(request.changed_node_ids)
        stale_ids = [node.node_id for node in parents]
        return self.store.mark_stale(stale_ids)


class FlatRetriever:
    """Flat leaf retrieval baseline
    Scores L0 nodes then keeps top items within token budget"""

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
        """Rank L0 nodes and keep best items in budget"""
        # score leafs by relevance recency and importance
        nodes = self.store.list_nodes(agent_id=agent_id, level=MemoryLevel.L0)
        candidates: list[CandidateScore] = []
        for node in nodes:
            rel = relevance_score(query, node.text)
            rec = recency_score(query_time, node.timestamp_end)
            imp = normalize_importance(node.importance_score)
            score = statistics.fmean([rel, rec, imp])
            candidates.append(CandidateScore(node=node, score=score, relevance=rel, recency=rec))
        # keep highest scores then pack within token cap
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
    """Summary construction pipeline
    Clusters leaf nodes then runs summarize plus verify before upsert"""

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
        """Build one summary level from source leaves"""
        # Keep the MVP summary builder on one hop for predictable provenance
        if request.source_level != MemoryLevel.L0 or request.target_level != MemoryLevel.L1:
            raise ValueError("The MVP only supports L0 to L1 summary construction.")
        nodes = self.store.list_nodes(agent_id=request.agent_id, level=request.source_level)
        clusters = self._cluster_nodes(nodes)
        built: list[MemoryNode] = []
        for cluster in clusters:
            if not self._should_summarize_cluster(cluster):
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
            # Create the summary node before verification so traces can point at a stable id
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
                commitments=summary_result.commitments,
                revisions=summary_result.revisions,
                preferences=summary_result.preferences,
                relationship_guidance=summary_result.relationship_guidance,
                self_model_updates=summary_result.self_model_updates,
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
            # Backfill parent links so retrieval can walk the tree upward
            for child in cluster:
                if summary_node.node_id not in child.parent_ids:
                    child.parent_ids.append(summary_node.node_id)
                    self.store.upsert_node(child)
            built.append(summary_node)
        return built

    def _should_summarize_cluster(self, cluster: list[MemoryNode]) -> bool:
        """Decide whether a cluster deserves a summary"""
        if len(cluster) >= 2:
            return True
        if not cluster:
            return False
        node = cluster[0]
        return node.importance_score >= 0.85 or self._contains_revision_signal(node.text)

    def _contains_revision_signal(self, text: str) -> bool:
        """Detect update language that merits summarization"""
        lowered = text.lower()
        return any(
            token in lowered
            for token in ["updated", "changed", "now", "current", "latest", "revision", "correct", "obsolete", "instead"]
        )

    def _contains_social_thread_signal(self, text: str) -> bool:
        """Detect interpersonal thread language"""
        lowered = text.lower()
        return any(
            token in lowered
            for token in [
                "prefer",
                "preference",
                "preferences",
                "dislike",
                "dislikes",
                "hate",
                "hates",
                "agenda",
                "agendas",
                "expectation",
                "expectations",
                "written",
                "check-in",
                "check-ins",
                "sync",
                "syncs",
                "improv",
                "surprise",
                "surprises",
                "follow-up",
                "communicat",
                "approach",
            ]
        )

    def _meaningful_cluster_entities(self, node: MemoryNode) -> set[str]:
        """Filter noisy entities from clustering"""
        stop_entities = {"follow", "day", "morning", "afternoon", "evening", "routine"}
        return {entity.lower() for entity in node.entities if entity and entity.lower() not in stop_entities}

    def _can_extend_social_thread_cluster(self, cluster: list[MemoryNode], node: MemoryNode) -> bool:
        """Allow social clusters to absorb closely related nodes"""
        if not cluster:
            return False
        node_entities = self._meaningful_cluster_entities(node)
        if not node_entities or not self._contains_social_thread_signal(node.text):
            return False
        cluster_entities = {entity for item in cluster for entity in self._meaningful_cluster_entities(item)}
        if not (node_entities & cluster_entities):
            return False
        if not any(self._contains_social_thread_signal(item.text) for item in cluster):
            return False
        latest = cluster[-1]
        social_thread_window = node.timestamp_start - latest.timestamp_end <= timedelta(
            hours=max(self.settings.time_window_hours, 72)
        )
        return social_thread_window

    def _cluster_nodes(self, nodes: list[MemoryNode]) -> list[list[MemoryNode]]:
        if not nodes:
            return []
        clusters: list[list[MemoryNode]] = []
        for node in nodes:
            social_target = next(
                (cluster for cluster in reversed(clusters) if self._can_extend_social_thread_cluster(cluster, node)),
                None,
            )
            if social_target is not None:
                social_target.append(node)
                continue
            if not clusters:
                clusters.append([node])
                continue
            current = clusters[-1]
            prev = current[-1]
            within_window = node.timestamp_start - prev.timestamp_end <= timedelta(hours=self.settings.time_window_hours)
            semantically_related = (
                jaccard_similarity(node.text, " ".join(item.text for item in current))
                >= self.settings.cluster_similarity_threshold
            )
            shared_topic = bool(set(node.topics) & {topic for item in current for topic in item.topics})
            shared_entity = bool(
                self._meaningful_cluster_entities(node)
                & {entity for item in current for entity in self._meaningful_cluster_entities(item)}
            )
            conflicting_social_thread = (
                not shared_entity
                and bool(self._meaningful_cluster_entities(node))
                and any(self._meaningful_cluster_entities(item) for item in current)
                and self._contains_social_thread_signal(node.text)
                and any(self._contains_social_thread_signal(item.text) for item in current)
            )
            important_context = max(item.importance_score for item in current + [node]) >= 0.8 and node.importance_score >= 0.6
            if (
                within_window
                and not conflicting_social_thread
                and (semantically_related or shared_topic or shared_entity or important_context)
            ):
                current.append(node)
            else:
                clusters.append([node])
        return clusters


class ContextPacker:
    """Prompt context packer
    Dedups overlap and enforces token budget during packing"""

    def pack(self, query: str, candidates: list[CandidateScore], token_budget: int) -> str:
        """Build compact context block within token budget"""
        lines = [f"Query: {query}", "Context:"]
        consumed = token_count(query)
        packed_texts: list[str] = []
        seen_nodes: set[str] = set()
        for candidate in candidates:
            if candidate.node.node_id in seen_nodes:
                continue
            overlap = max((jaccard_similarity(candidate.node.text, existing) for existing in packed_texts), default=0.0)
            if overlap >= 0.72:
                continue
            snippet = f"[{candidate.node.level.value}/{candidate.node.node_type.value}] {candidate.node.text}"
            snippet_tokens = token_count(snippet)
            if consumed + snippet_tokens > token_budget:
                continue
            lines.append(snippet)
            consumed += snippet_tokens
            seen_nodes.add(candidate.node.node_id)
            packed_texts.append(candidate.node.text)
        return "\n".join(lines)

class AgentLoopAdapter:
    """Convenience adapter for agent actions
    Normalizes observe reflect plan writes through MemoryStore"""

    def __init__(self, services: "MemoryService") -> None:
        self.services = services

    def observe(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.5) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.EPISODE)

    def reflect(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.7) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.REFLECTION)

    def plan(self, agent_id: str, text: str, timestamp: datetime, importance_score: float = 0.8) -> MemoryNode:
        return self.services.store.write_l0(agent_id, text, timestamp, importance_score, NodeType.PLAN)


class MemoryService:
    """Top level service facade for app usage
    Wires storage models retrieval eval and trace recording paths"""

    def __init__(self, settings: Settings) -> None:
        # wire core dependencies once per service instance
        self.settings = settings
        self.db = self._build_database(settings)
        self.store = MemoryStore(self.db, settings.prompt_version, settings.model_version)
        if settings.auto_create_schema or self._using_database_fallback:
            self.store.ensure_schema()
        model_client, provider = build_model_client(settings)
        self.summarizer = ModelBackedSummarizer(model_client, provider, settings)
        self.verifier = ModelBackedVerifier(model_client, provider, settings)
        self.answerer = ModelBackedAnswerer(model_client, provider, settings)
        self.answer_verifier = ModelBackedAnswerVerifier(model_client, provider, settings)
        self.refresh_policy = RefreshPolicy(self.store)
        self.flat_retriever = FlatRetriever(self.store)
        self.tree_builder = TreeBuilder(self.store, self.summarizer, self.verifier, settings)
        self.hierarchical_retriever = HierarchicalRetriever(self.store, self.flat_retriever, settings)
        self.context_packer = ContextPacker()
        self.agent_loop = AgentLoopAdapter(self)

    def _build_database(self, settings: Settings) -> Database:
        self._using_database_fallback = False
        primary_db = Database(settings.database_url)
        if not settings.database_url.startswith(("postgresql", "postgres")):
            return primary_db
        try:
            primary_db.verify_connection()
            return primary_db
        except OperationalError:
            fallback_url = settings.database_fallback_url
            if (
                not settings.database_fallback_on_unavailable
                or not fallback_url
                or fallback_url == settings.database_url
            ):
                raise
            logger.warning(
                "Primary database unavailable at %s; falling back to %s for local service startup.",
                settings.database_url,
                fallback_url,
            )
            self._using_database_fallback = True
            return Database(fallback_url)

    def build_summaries(self, request: BuildSummariesRequest) -> list[MemoryNode]:
        """Build summaries for an agent"""
        return self.tree_builder.build_level(request)

    def ingest_batch(self, request: BatchIngestMemoriesRequest) -> BatchIngestMemoriesResponse:
        """Ingest multiple L0 memories with optional dedupe and summary build."""
        records = list(request.records)
        if request.sort_by_timestamp:
            records.sort(key=lambda item: normalize_datetime(item.timestamp))

        ingested_nodes: list[MemoryNode] = []
        duplicate_event_ids: list[str] = []
        latest_timestamp: datetime | None = None
        for record in records:
            normalized_timestamp = normalize_datetime(record.timestamp)
            latest_timestamp = normalized_timestamp if latest_timestamp is None else max(latest_timestamp, normalized_timestamp)
            if record.event_id and not record.allow_duplicate:
                existing = self.store.find_existing_l0_by_event_id(request.agent_id, record.event_id)
                if existing is not None:
                    duplicate_event_ids.append(record.event_id)
                    continue
            node = self.store.write_l0(
                agent_id=request.agent_id,
                text=record.text,
                timestamp=record.timestamp,
                importance_score=record.importance_score,
                node_type=record.node_type,
                entities=record.entities,
                topics=record.topics,
                source_type=record.source_type,
                source_id=record.source_id,
                event_id=record.event_id,
                allow_duplicate=record.allow_duplicate,
            )
            ingested_nodes.append(node)

        built_summary_count = 0
        if request.build_summaries_after_ingest and ingested_nodes:
            built_summary_count = len(
                self.build_summaries(
                    BuildSummariesRequest(
                        agent_id=request.agent_id,
                        query_time=latest_timestamp or datetime.utcnow(),
                    )
                )
            )

        return BatchIngestMemoriesResponse(
            agent_id=request.agent_id,
            received_count=len(request.records),
            ingested_count=len(ingested_nodes),
            duplicate_count=len(duplicate_event_ids),
            built_summary_count=built_summary_count,
            node_ids=[node.node_id for node in ingested_nodes],
            duplicates=duplicate_event_ids,
        )

    def retrieve(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        mode: QueryMode,
        token_budget: int,
        branch_limit: int,
        generate_answer: bool = True,
        verify_answer: bool = False,
    ) -> RetrieveResponse:
        """Run hierarchical retrieval and persist trace"""
        retrieved, depth, trace_entries, routing_attribution = self.hierarchical_retriever.retrieve(
            agent_id=agent_id,
            query=query,
            query_time=query_time,
            mode=mode,
            token_budget=token_budget,
            branch_limit=branch_limit,
        )
        packed = self.context_packer.pack(query, retrieved, token_budget)
        diagnostics = build_retrieval_diagnostics(retrieved, trace_entries, packed, routing_attribution=routing_attribution)
        answer_result = None
        answer_verification = None
        if generate_answer:
            answer_result, answer_trace = self.answerer.generate(
                agent_id=agent_id,
                query=query,
                retrieved_nodes=[item.node for item in retrieved],
                packed_context=packed,
            )
            self.store.write_model_trace(answer_trace)
            if verify_answer and answer_result.text.strip():
                answer_verification, verification_trace = self.answer_verifier.verify(
                    agent_id=agent_id,
                    query=query,
                    answer=answer_result,
                    supports=[item.node for item in retrieved],
                )
                self.store.write_model_trace(verification_trace)
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
            answer=answer_result,
            answer_verification=answer_verification,
        )

    def retrieve_flat(
        self,
        agent_id: str,
        query: str,
        query_time: datetime,
        token_budget: int,
        branch_limit: int,
    ) -> RetrieveResponse:
        """Run baseline flat retrieval and persist trace"""
        retrieved = self.flat_retriever.retrieve(agent_id, query, query_time, token_budget, limit=branch_limit)
        packed = self.context_packer.pack(query, retrieved, token_budget)
        trace_entries = [
            make_retrieval_trace_entry(
                item,
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

    def social_state(self, agent_id: str) -> SocialStateDigestResponse:
        return build_social_state_digest(
            agent_id=agent_id,
            nodes=self.store.list_nodes(agent_id=agent_id, include_stale=True),
        )

    def retrieval_traces(self, agent_id: str | None = None, limit: int = 20) -> list[RetrievalTrace]:
        return self.store.list_retrieval_traces(agent_id=agent_id, limit=limit)

    def model_traces(self, agent_id: str | None = None, limit: int = 20):
        return self.store.list_model_traces(agent_id=agent_id, limit=limit)

    def eval_runs(self) -> list[dict]:
        return self.store.list_eval_runs()

    def record_eval(self, result: EvalRunResult) -> None:
        self.store.write_eval_run(result.scenario_name, json.dumps(dump_model(result), default=str))
