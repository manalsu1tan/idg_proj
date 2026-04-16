from __future__ import annotations

"""FastAPI app routes
Exposes memory ingest retrieval eval and report endpoints"""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from apps.api.dependencies import get_service
from packages.evals.ablation import build_ablation_report, render_ablation_markdown, run_all_ablations
from packages.evals.report import build_report_payload, render_markdown_report
from packages.evals.runner import run_all
from packages.memory_core.services import MemoryService
from packages.schemas.models import (
    AgentTreeResponse,
    BuildSummariesRequest,
    EvalRequest,
    EvalRunResult,
    IngestMemoryRequest,
    ModelTrace,
    NodeProvenance,
    RefreshRequest,
    RetrievalTrace,
    RetrieveRequest,
    RetrieveResponse,
    TimelineResponse,
)

app = FastAPI(title="Memory Tree", version="0.1.0")
UI_DIR = Path(__file__).resolve().parents[1] / "ui" / "static"
# mount static ui assets when bundle exists
if UI_DIR.exists():
    app.mount("/ui/assets", StaticFiles(directory=UI_DIR), name="ui-assets")


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    """Liveness endpoint"""
    return {"status": "ok"}


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
    """Run benchmark eval suite
    Executes scenarios and returns persisted eval run results"""
    del service
    return run_all()


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


@app.get("/ui")
def get_ui() -> FileResponse:
    """Serve ui index page"""
    return FileResponse(UI_DIR / "index.html")
