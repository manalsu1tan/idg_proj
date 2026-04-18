from __future__ import annotations

"""FastAPI app routes
Exposes memory ingest retrieval eval and report endpoints"""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel
from datetime import datetime, timedelta
import uuid

from apps.api.dependencies import get_service
from packages.evals.ablation import build_ablation_report, render_ablation_markdown, run_all_ablations
from packages.evals.report import build_report_payload, render_markdown_report
from packages.evals.runner import run_selected
from packages.evals.scenarios import get_scenario, scenario_timestamp
from packages.memory_core.services import MemoryService
from packages.memory_core.utils import extract_entities, pseudo_embedding, source_hash, token_count, unique_topics
from packages.schemas.models import (
    AgentTreeResponse,
    BuildSummariesRequest,
    CreatedBy,
    EvalRequest,
    EvalRunResult,
    IngestMemoryRequest,
    MemoryLevel,
    MemoryNode,
    ModelTrace,
    NodeType,
    NodeProvenance,
    QualityStatus,
    RefreshRequest,
    RetrievalTrace,
    RetrieveRequest,
    RetrieveResponse,
    TimelineResponse,
)

app = FastAPI(title="Memory Tree", version="0.1.0")
UI_DIR = Path(__file__).resolve().parents[1] / "ui" / "static"
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
DEFAULT_DEMO_SCENARIO_NAME = "stakeholder_handoff_demo_v1"
DEFAULT_DEMO_AGENT_ID = "demo-agent-stakeholder-handoff"
DEFAULT_DEMO_QUERY_PRESETS = [
    {
        "label": "Sasha vs. Leah",
        "query": "How should I approach Sasha differently from Leah?",
    },
    {
        "label": "Current deliverable",
        "query": "What am I actually presenting now: the prototype or something else?",
    },
    {
        "label": "AV owner and risk",
        "query": "Who owns AV setup, and what risk should I prepare for?",
    },
    {
        "label": "Sasha pre-read",
        "query": "What should I send Sasha before the workshop?",
    },
    {
        "label": "Avoid with Sasha",
        "query": "What should I avoid doing with Sasha on the day of the workshop?",
    },
    {
        "label": "Highest-risk gap",
        "query": "If I only have time for one prep task this morning, what is the highest-risk gap?",
    },
    {
        "label": "Evidence for Sasha",
        "query": "Which memories support the recommendation for Sasha?",
    },
]


class NoCacheStaticFiles(StaticFiles):
    """Static file handler that disables browser caching for rapid UI iteration."""

    def file_response(self, full_path, stat_result, scope, status_code: int = 200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers.update(NO_CACHE_HEADERS)
        return response


# mount static ui assets when bundle exists
if UI_DIR.exists():
    app.mount("/ui/assets", NoCacheStaticFiles(directory=UI_DIR), name="ui-assets")


class DemoSeedRequest(BaseModel):
    scenario_name: str = DEFAULT_DEMO_SCENARIO_NAME
    force: bool = True


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    """Liveness endpoint"""
    return {"status": "ok"}


def _demo_l0_node(
    *,
    service: MemoryService,
    agent_id: str,
    text: str,
    timestamp: datetime,
    importance: float,
    node_type: NodeType = NodeType.EPISODE,
) -> MemoryNode:
    timestamp = timestamp.replace(tzinfo=None)
    return MemoryNode(
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
        importance_score=importance,
        entities=extract_entities(text),
        topics=unique_topics(text),
        commitments=[],
        revisions=[],
        preferences=[],
        relationship_guidance=[],
        self_model_updates=[],
        version=1,
        stale_flag=False,
        summary_policy_id="demo.seed.v2",
        quality_status=QualityStatus.VERIFIED,
        quality_scores={"faithfulness": 1.0, "coverage": 1.0},
        token_count=token_count(text),
        source_hash=source_hash([text, timestamp.isoformat(), "l0"]),
        created_by=CreatedBy.AGENT,
        prompt_version=service.store.prompt_version,
        model_version=service.store.model_version,
    )


def _demo_summary_node(
    *,
    service: MemoryService,
    agent_id: str,
    level: MemoryLevel,
    text: str,
    timestamp: datetime,
    child_ids: list[str],
    support_ids: list[str],
    parent_ids: list[str] | None = None,
) -> MemoryNode:
    timestamp = timestamp.replace(tzinfo=None)
    return MemoryNode(
        node_id=str(uuid.uuid4()),
        agent_id=agent_id,
        level=level,
        node_type=NodeType.SUMMARY,
        text=text,
        timestamp_start=timestamp,
        timestamp_end=timestamp,
        parent_ids=parent_ids or [],
        child_ids=child_ids,
        support_ids=support_ids,
        embedding=pseudo_embedding(text),
        importance_score=0.9,
        entities=extract_entities(text),
        topics=unique_topics(text),
        commitments=[],
        revisions=[],
        preferences=[],
        relationship_guidance=[],
        self_model_updates=[],
        version=1,
        stale_flag=False,
        summary_policy_id="demo.seed.v2",
        quality_status=QualityStatus.VERIFIED,
        quality_scores={"faithfulness": 0.98, "coverage": 0.95},
        token_count=token_count(text),
        source_hash=source_hash([text] + child_ids + support_ids + [level.value]),
        created_by=CreatedBy.SUMMARIZER,
        prompt_version=service.store.prompt_version,
        model_version=service.store.model_version,
    )


def _default_demo_payload(agent_id: str = DEFAULT_DEMO_AGENT_ID) -> dict[str, object]:
    return {
        "agent_id": agent_id,
        "scenario_name": DEFAULT_DEMO_SCENARIO_NAME,
        "query": DEFAULT_DEMO_QUERY_PRESETS[0]["query"],
        "query_presets": DEFAULT_DEMO_QUERY_PRESETS,
    }


def _seed_stakeholder_handoff_demo_graph(service: MemoryService, agent_id: str) -> dict[str, object]:
    service.store.delete_agent_data(agent_id)
    t0 = datetime(2025, 2, 3, 9, 0, 0)

    l0_nodes = [
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Sasha asked for a written agenda before the customer workshop and said last-minute pivots make her uneasy.",
            timestamp=t0,
            importance=0.92,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Leah said she is fine with a loose brainstorm format and does not need a formal pre-read.",
            timestamp=t0 + timedelta(hours=5),
            importance=0.84,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Nadia confirmed she will own projector and audio setup, but wants the final equipment list by Thursday.",
            timestamp=t0 + timedelta(days=1, hours=1),
            importance=0.88,
            node_type=NodeType.PLAN,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Initial plan was to show the interactive prototype during the workshop.",
            timestamp=t0 + timedelta(days=1, hours=7),
            importance=0.82,
            node_type=NodeType.PLAN,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Customer feedback changed the plan: the interactive prototype is out, and the final deliverable is now a narrated walkthrough.",
            timestamp=t0 + timedelta(days=2, hours=2),
            importance=0.96,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Follow-up with Sasha: send expectations and sequencing in writing before the session.",
            timestamp=t0 + timedelta(days=2, hours=6),
            importance=0.9,
            node_type=NodeType.REFLECTION,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Follow-up with Leah: a quick informal sync the morning of the workshop is enough.",
            timestamp=t0 + timedelta(days=3, minutes=30),
            importance=0.79,
            node_type=NodeType.REFLECTION,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Nadia flagged one risk: the conference room projector has failed intermittently this week.",
            timestamp=t0 + timedelta(days=3, hours=4),
            importance=0.91,
            node_type=NodeType.REFLECTION,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Added backup plan: bring HDMI adapter, spare clicker, and a local copy of the narrated walkthrough.",
            timestamp=t0 + timedelta(days=3, hours=8),
            importance=0.9,
            node_type=NodeType.PLAN,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Sasha clarified she wants the final talking points, not just a high-level outline.",
            timestamp=t0 + timedelta(days=4, minutes=30),
            importance=0.93,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Leah offered to handle live discussion if the room energy is good.",
            timestamp=t0 + timedelta(days=4, hours=3),
            importance=0.74,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Confirmed final ownership: Nadia handles AV, Sasha signs off on messaging, and Leah supports live facilitation.",
            timestamp=t0 + timedelta(days=4, hours=7),
            importance=0.94,
            node_type=NodeType.REFLECTION,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Reminder to myself: do not surprise Sasha with format changes on the day of the workshop.",
            timestamp=t0 + timedelta(days=5),
            importance=0.87,
            node_type=NodeType.REFLECTION,
        ),
        _demo_l0_node(
            service=service,
            agent_id=agent_id,
            text="Reminder to myself: Leah is comfortable adapting in the room if the customer discussion shifts.",
            timestamp=t0 + timedelta(days=5, hours=2),
            importance=0.68,
            node_type=NodeType.REFLECTION,
        ),
    ]
    for node in l0_nodes:
        service.store.upsert_node(node)

    by_text = {node.text: node for node in l0_nodes}
    sasha_children = [
        by_text["Sasha asked for a written agenda before the customer workshop and said last-minute pivots make her uneasy."].node_id,
        by_text["Follow-up with Sasha: send expectations and sequencing in writing before the session."].node_id,
        by_text["Sasha clarified she wants the final talking points, not just a high-level outline."].node_id,
        by_text["Reminder to myself: do not surprise Sasha with format changes on the day of the workshop."].node_id,
    ]
    leah_children = [
        by_text["Leah said she is fine with a loose brainstorm format and does not need a formal pre-read."].node_id,
        by_text["Follow-up with Leah: a quick informal sync the morning of the workshop is enough."].node_id,
        by_text["Leah offered to handle live discussion if the room energy is good."].node_id,
        by_text["Reminder to myself: Leah is comfortable adapting in the room if the customer discussion shifts."].node_id,
    ]
    revision_children = [
        by_text["Initial plan was to show the interactive prototype during the workshop."].node_id,
        by_text["Customer feedback changed the plan: the interactive prototype is out, and the final deliverable is now a narrated walkthrough."].node_id,
    ]
    logistics_children = [
        by_text["Nadia confirmed she will own projector and audio setup, but wants the final equipment list by Thursday."].node_id,
        by_text["Nadia flagged one risk: the conference room projector has failed intermittently this week."].node_id,
        by_text["Added backup plan: bring HDMI adapter, spare clicker, and a local copy of the narrated walkthrough."].node_id,
        by_text["Confirmed final ownership: Nadia handles AV, Sasha signs off on messaging, and Leah supports live facilitation."].node_id,
    ]

    by_text["Sasha asked for a written agenda before the customer workshop and said last-minute pivots make her uneasy."].support_ids = [
        by_text["Follow-up with Sasha: send expectations and sequencing in writing before the session."].node_id,
        by_text["Sasha clarified she wants the final talking points, not just a high-level outline."].node_id,
    ]
    by_text["Leah said she is fine with a loose brainstorm format and does not need a formal pre-read."].support_ids = [
        by_text["Follow-up with Leah: a quick informal sync the morning of the workshop is enough."].node_id,
        by_text["Leah offered to handle live discussion if the room energy is good."].node_id,
    ]
    by_text["Initial plan was to show the interactive prototype during the workshop."].support_ids = [
        by_text["Customer feedback changed the plan: the interactive prototype is out, and the final deliverable is now a narrated walkthrough."].node_id,
    ]
    by_text["Nadia flagged one risk: the conference room projector has failed intermittently this week."].support_ids = [
        by_text["Added backup plan: bring HDMI adapter, spare clicker, and a local copy of the narrated walkthrough."].node_id,
        by_text["Confirmed final ownership: Nadia handles AV, Sasha signs off on messaging, and Leah supports live facilitation."].node_id,
    ]
    for node in l0_nodes:
        service.store.upsert_node(node)

    l1_sasha = _demo_summary_node(
        service=service,
        agent_id=agent_id,
        level=MemoryLevel.L1,
        text="Sasha communication thread: written expectations, clear agendas, final talking points, and no day-of surprises.",
        timestamp=t0 + timedelta(days=6),
        child_ids=sasha_children,
        support_ids=sasha_children,
    )
    l1_leah = _demo_summary_node(
        service=service,
        agent_id=agent_id,
        level=MemoryLevel.L1,
        text="Leah collaboration thread: casual syncs, loose structure, and live adaptation are acceptable.",
        timestamp=t0 + timedelta(days=6, hours=1),
        child_ids=leah_children,
        support_ids=leah_children,
    )
    l1_revision = _demo_summary_node(
        service=service,
        agent_id=agent_id,
        level=MemoryLevel.L1,
        text="Deliverable revision thread: the workshop moved from an interactive prototype to a narrated walkthrough after customer feedback.",
        timestamp=t0 + timedelta(days=6, hours=2),
        child_ids=revision_children,
        support_ids=revision_children,
    )
    l1_logistics = _demo_summary_node(
        service=service,
        agent_id=agent_id,
        level=MemoryLevel.L1,
        text="Logistics and ownership thread: Nadia owns AV, the projector is unreliable, and backup equipment plus a local file reduce workshop risk.",
        timestamp=t0 + timedelta(days=6, hours=3),
        child_ids=logistics_children,
        support_ids=logistics_children,
    )
    for node in [l1_sasha, l1_leah, l1_revision, l1_logistics]:
        service.store.upsert_node(node)

    l2_workshop = _demo_summary_node(
        service=service,
        agent_id=agent_id,
        level=MemoryLevel.L2,
        text="Workshop readiness summary: tailor written messaging for Sasha, keep Leah loose and adaptive, present the narrated walkthrough, and rely on Nadia's AV plan plus hardware backups.",
        timestamp=t0 + timedelta(days=7),
        child_ids=[l1_sasha.node_id, l1_leah.node_id, l1_revision.node_id, l1_logistics.node_id],
        support_ids=[l1_sasha.node_id, l1_leah.node_id, l1_revision.node_id, l1_logistics.node_id],
    )
    service.store.upsert_node(l2_workshop)

    parent_map = {
        **{node_id: l1_sasha.node_id for node_id in sasha_children},
        **{node_id: l1_leah.node_id for node_id in leah_children},
        **{node_id: l1_revision.node_id for node_id in revision_children},
        **{node_id: l1_logistics.node_id for node_id in logistics_children},
        l1_sasha.node_id: l2_workshop.node_id,
        l1_leah.node_id: l2_workshop.node_id,
        l1_revision.node_id: l2_workshop.node_id,
        l1_logistics.node_id: l2_workshop.node_id,
    }
    all_nodes = l0_nodes + [l1_sasha, l1_leah, l1_revision, l1_logistics, l2_workshop]
    for node in all_nodes:
        parent_id = parent_map.get(node.node_id)
        node.parent_ids = [parent_id] if parent_id else []
        service.store.upsert_node(node)

    return {
        **_default_demo_payload(agent_id),
        "l0_count": len(l0_nodes),
        "l1_count": 4,
        "l2_count": 1,
        "total_count": len(all_nodes),
    }


def _seed_benchmark_demo_scenario(service: MemoryService, scenario_name: str) -> dict[str, int | str]:
    scenario = get_scenario(scenario_name)
    service.store.delete_agent_data(scenario.agent_id)
    for event in scenario.events:
        service.agent_loop.observe(
            agent_id=scenario.agent_id,
            text=event.text,
            timestamp=scenario_timestamp(event.day_offset),
            importance_score=event.importance,
        )
    service.build_summaries(
        BuildSummariesRequest(
            agent_id=scenario.agent_id,
            query_time=scenario_timestamp(scenario.query_day_offset),
        )
    )
    nodes = service.store.list_nodes(agent_id=scenario.agent_id, include_stale=True)
    return {
        "agent_id": scenario.agent_id,
        "scenario_name": scenario.name,
        "query": scenario.query,
        "l0_count": sum(1 for node in nodes if node.level == MemoryLevel.L0),
        "l1_count": sum(1 for node in nodes if node.level == MemoryLevel.L1),
        "l2_count": sum(1 for node in nodes if node.level == MemoryLevel.L2),
        "total_count": len(nodes),
    }


@app.post("/v1/memories/ingest")
def ingest_memory(request: IngestMemoryRequest, service: MemoryService = Depends(get_service)):
    """Ingest one L0 memory node"""
    return service.store.write_l0(
        agent_id=request.agent_id,
        text=request.text,
        timestamp=request.timestamp,
        importance_score=request.importance_score,
        node_type=request.node_type,
        entities=request.entities,
        topics=request.topics,
    )


@app.post("/v1/memories/retrieve", response_model=RetrieveResponse)
def retrieve_memory(request: RetrieveRequest, service: MemoryService = Depends(get_service)) -> RetrieveResponse:
    """Run hierarchical retrieval for request query
    Returns packed context selected nodes diagnostics and trace metadata"""
    return service.retrieve(
        agent_id=request.agent_id,
        query=request.query,
        query_time=request.query_time,
        mode=request.mode,
        token_budget=request.token_budget,
        branch_limit=request.branch_limit,
        generate_answer=request.generate_answer,
        verify_answer=request.verify_answer,
    )


@app.post("/v1/memories/context-pack", response_model=RetrieveResponse)
def context_pack(request: RetrieveRequest, service: MemoryService = Depends(get_service)) -> RetrieveResponse:
    """Run retrieval path used for context packing"""
    return service.retrieve(
        agent_id=request.agent_id,
        query=request.query,
        query_time=request.query_time,
        mode=request.mode,
        token_budget=request.token_budget,
        branch_limit=request.branch_limit,
        generate_answer=request.generate_answer,
        verify_answer=request.verify_answer,
    )


@app.post("/v1/memories/refresh")
def refresh_memory(request: RefreshRequest, service: MemoryService = Depends(get_service)):
    """Refresh stale summaries"""
    return service.refresh(request)


@app.post("/v1/summaries/build")
def build_summaries(request: BuildSummariesRequest, service: MemoryService = Depends(get_service)):
    """Build summaries from current agent leaves"""
    return service.build_summaries(request)


@app.post("/v1/evals/run", response_model=list[EvalRunResult])
def run_evals(_: EvalRequest, service: MemoryService = Depends(get_service)) -> list[EvalRunResult]:
    """Run demo eval subset
    Uses quick scenario set for fast UI turnaround"""
    del service
    return run_selected(quick=True)


@app.post("/v1/evals/ablations/run")
def run_ablation_evals(_: EvalRequest, service: MemoryService = Depends(get_service)):
    """Run ablation suite and return assembled report
    Useful for policy comparison and regression analysis endpoints"""
    del service
    results = run_all_ablations()
    return build_ablation_report(results)


@app.get("/v1/evals/runs")
def list_eval_runs(service: MemoryService = Depends(get_service)):
    """List stored eval runs"""
    return service.eval_runs()


@app.get("/v1/evals/report")
def get_eval_report(service: MemoryService = Depends(get_service)):
    """Return eval report payload"""
    return build_report_payload(service.eval_runs())


@app.get("/v1/evals/report.md")
def get_eval_report_markdown(service: MemoryService = Depends(get_service)) -> PlainTextResponse:
    """Return eval report markdown"""
    report = build_report_payload(service.eval_runs())
    return PlainTextResponse(render_markdown_report(report), media_type="text/markdown")


@app.get("/v1/evals/ablations/report.md")
def get_ablation_report_markdown(service: MemoryService = Depends(get_service)) -> PlainTextResponse:
    """Return ablation report markdown"""
    del service
    report = build_ablation_report(run_all_ablations())
    return PlainTextResponse(render_ablation_markdown(report), media_type="text/markdown")


@app.get("/v1/nodes/{node_id}")
def get_node(node_id: str, service: MemoryService = Depends(get_service)):
    """Get node by id"""
    node = service.store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    return node


@app.get("/v1/nodes/{node_id}/provenance", response_model=NodeProvenance)
def get_provenance(node_id: str, service: MemoryService = Depends(get_service)) -> NodeProvenance:
    """Get node lineage view"""
    try:
        return service.node_provenance(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="node not found") from exc


@app.get("/v1/nodes/{node_id}/children")
def get_children(node_id: str, service: MemoryService = Depends(get_service)):
    """Get direct child nodes"""
    node = service.store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    return service.store.child_nodes(node_id)


@app.get("/v1/agents/{agent_id}/timeline", response_model=TimelineResponse)
def get_timeline(agent_id: str, service: MemoryService = Depends(get_service)) -> TimelineResponse:
    """Get timeline projection for agent"""
    return service.timeline(agent_id)


@app.get("/v1/agents/{agent_id}/tree", response_model=AgentTreeResponse)
def get_tree(agent_id: str, service: MemoryService = Depends(get_service)) -> AgentTreeResponse:
    """Get tree projection for agent"""
    return service.agent_tree(agent_id)


@app.get("/v1/retrievals", response_model=list[RetrievalTrace])
def get_retrievals(agent_id: str | None = None, limit: int = 20, service: MemoryService = Depends(get_service)) -> list[RetrievalTrace]:
    """List retrieval traces with optional filter"""
    return service.retrieval_traces(agent_id=agent_id, limit=limit)


@app.get("/v1/model-traces", response_model=list[ModelTrace])
def get_model_traces(agent_id: str | None = None, limit: int = 20, service: MemoryService = Depends(get_service)) -> list[ModelTrace]:
    """List model traces with optional filter"""
    return service.model_traces(agent_id=agent_id, limit=limit)


@app.post("/v1/demo/seed-complex")
def seed_complex_demo(request: DemoSeedRequest, service: MemoryService = Depends(get_service)):
    """Seed the dedicated inspector demo scenario or a benchmark-backed fallback."""
    if request.scenario_name == DEFAULT_DEMO_SCENARIO_NAME:
        existing = service.store.list_nodes(agent_id=DEFAULT_DEMO_AGENT_ID, include_stale=True)
        if existing and not request.force:
            counts = {
                "l0_count": sum(1 for node in existing if node.level == MemoryLevel.L0),
                "l1_count": sum(1 for node in existing if node.level == MemoryLevel.L1),
                "l2_count": sum(1 for node in existing if node.level == MemoryLevel.L2),
                "total_count": len(existing),
            }
            return {"seeded": False, **_default_demo_payload(), **counts}
        stats = _seed_stakeholder_handoff_demo_graph(service, DEFAULT_DEMO_AGENT_ID)
        return {"seeded": True, **stats}

    scenario = get_scenario(request.scenario_name)
    existing = service.store.list_nodes(agent_id=scenario.agent_id, include_stale=True)
    if existing and not request.force:
        return {"seeded": False, "reason": "agent already has data", "agent_id": scenario.agent_id, "node_count": len(existing)}
    stats = _seed_benchmark_demo_scenario(service, request.scenario_name)
    return {"seeded": True, **stats}


@app.get("/ui")
def get_ui() -> FileResponse:
    """Serve ui index page"""
    return FileResponse(UI_DIR / "index.html", headers=NO_CACHE_HEADERS)
