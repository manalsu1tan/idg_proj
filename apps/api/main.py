from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from apps.api.dependencies import get_service
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
if UI_DIR.exists():
    app.mount("/ui/assets", StaticFiles(directory=UI_DIR), name="ui-assets")


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/memories/ingest")
def ingest_memory(request: IngestMemoryRequest, service: MemoryService = Depends(get_service)):
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
    return service.refresh(request)


@app.post("/v1/summaries/build")
def build_summaries(request: BuildSummariesRequest, service: MemoryService = Depends(get_service)):
    return service.build_summaries(request)


@app.post("/v1/evals/run", response_model=list[EvalRunResult])
def run_evals(_: EvalRequest, service: MemoryService = Depends(get_service)) -> list[EvalRunResult]:
    del service
    return run_all()


@app.get("/v1/evals/runs")
def list_eval_runs(service: MemoryService = Depends(get_service)):
    return service.eval_runs()


@app.get("/v1/evals/report")
def get_eval_report(service: MemoryService = Depends(get_service)):
    return build_report_payload(service.eval_runs())


@app.get("/v1/evals/report.md")
def get_eval_report_markdown(service: MemoryService = Depends(get_service)) -> PlainTextResponse:
    report = build_report_payload(service.eval_runs())
    return PlainTextResponse(render_markdown_report(report), media_type="text/markdown")


@app.get("/v1/nodes/{node_id}")
def get_node(node_id: str, service: MemoryService = Depends(get_service)):
    node = service.store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    return node


@app.get("/v1/nodes/{node_id}/provenance", response_model=NodeProvenance)
def get_provenance(node_id: str, service: MemoryService = Depends(get_service)) -> NodeProvenance:
    try:
        return service.node_provenance(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="node not found") from exc


@app.get("/v1/nodes/{node_id}/children")
def get_children(node_id: str, service: MemoryService = Depends(get_service)):
    node = service.store.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    return service.store.child_nodes(node_id)


@app.get("/v1/agents/{agent_id}/timeline", response_model=TimelineResponse)
def get_timeline(agent_id: str, service: MemoryService = Depends(get_service)) -> TimelineResponse:
    return service.timeline(agent_id)


@app.get("/v1/agents/{agent_id}/tree", response_model=AgentTreeResponse)
def get_tree(agent_id: str, service: MemoryService = Depends(get_service)) -> AgentTreeResponse:
    return service.agent_tree(agent_id)


@app.get("/v1/retrievals", response_model=list[RetrievalTrace])
def get_retrievals(agent_id: str | None = None, limit: int = 20, service: MemoryService = Depends(get_service)) -> list[RetrievalTrace]:
    return service.retrieval_traces(agent_id=agent_id, limit=limit)


@app.get("/v1/model-traces", response_model=list[ModelTrace])
def get_model_traces(agent_id: str | None = None, limit: int = 20, service: MemoryService = Depends(get_service)) -> list[ModelTrace]:
    return service.model_traces(agent_id=agent_id, limit=limit)


@app.get("/ui")
def get_ui() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")
