const state = {
  agentId: "benchmark-agent-delayed-commitment",
  selectedNodeId: null,
};

const timelineEl = document.getElementById("timeline");
const treeViewEl = document.getElementById("tree-view");
const nodeDetailEl = document.getElementById("node-detail");
const retrievalResultEl = document.getElementById("retrieval-result");
const retrievalTracesEl = document.getElementById("retrieval-traces");
const modelTracesEl = document.getElementById("model-traces");
const evalRunsEl = document.getElementById("eval-runs");

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function badge(label, extraClass = "") {
  return `<span class="badge ${extraClass}">${label}</span>`;
}

function renderTimeline(nodes) {
  if (!nodes.length) {
    timelineEl.innerHTML = `<div class="empty-state">No memories found for this agent.</div>`;
    return;
  }
  timelineEl.innerHTML = nodes
    .map(
      (node) => `
      <article class="timeline-card" data-node-id="${node.node_id}">
        <div class="timeline-meta">
          ${badge(node.level)}
          ${badge(node.node_type)}
          ${node.stale_flag ? badge("stale", "warn") : ""}
          ${badge(node.quality_status)}
        </div>
        <strong>${new Date(node.timestamp_start).toLocaleString()}</strong>
        <p>${node.text}</p>
      </article>
    `,
    )
    .join("");
  document.querySelectorAll(".timeline-card").forEach((card) => {
    card.addEventListener("click", () => selectNode(card.dataset.nodeId));
  });
}

function renderTreeNode(treeNode) {
  return `
    <div class="tree-node">
      <div class="timeline-meta">
        ${badge(treeNode.node.level)}
        ${badge(treeNode.node.node_type)}
      </div>
      <strong>${treeNode.node.text}</strong>
      ${
        treeNode.children?.length
          ? `<div class="tree-children">${treeNode.children.map((child) => renderTreeNode(child)).join("")}</div>`
          : ""
      }
    </div>
  `;
}

function renderTree(tree) {
  if (!tree.roots?.length) {
    treeViewEl.innerHTML = `<div class="empty-state">No hierarchy built yet.</div>`;
    return;
  }
  treeViewEl.innerHTML = tree.roots.map((root) => renderTreeNode(root)).join("");
}

function renderNodeDetail(provenance) {
  const root = provenance.root;
  nodeDetailEl.innerHTML = `
    <div class="detail-grid">
      <div class="detail-card">
        <div class="timeline-meta">
          ${badge(root.level)}
          ${badge(root.node_type)}
          ${badge(root.quality_status)}
          ${root.stale_flag ? badge("stale", "warn") : ""}
        </div>
        <strong>${root.text}</strong>
        <p class="muted">Version ${root.version} • ${new Date(root.timestamp_start).toLocaleString()}</p>
      </div>
      <div class="detail-card">
        <strong>Supports</strong>
        <ul>
          ${provenance.supports.map((node) => `<li>${node.text}</li>`).join("") || "<li>No supports</li>"}
        </ul>
      </div>
      <div class="detail-card">
        <strong>Ancestors</strong>
        <ul>
          ${provenance.ancestors.map((node) => `<li>${node.text}</li>`).join("") || "<li>No ancestors</li>"}
        </ul>
      </div>
      <div class="detail-card">
        <strong>Children</strong>
        <ul>
          ${provenance.descendants.map((node) => `<li>${node.text}</li>`).join("") || "<li>No children</li>"}
        </ul>
      </div>
    </div>
  `;
}

function renderRetrievalResult(result) {
  retrievalResultEl.innerHTML = `
    <div class="detail-card">
      <div class="timeline-meta">
        ${badge(`depth ${result.retrieval_depth}`)}
        ${badge(`budget ${result.token_budget}`)}
        ${badge(result.mode)}
      </div>
      <div class="score-row muted">
        <span>nodes ${result.diagnostics.retrieved_node_count}</span>
        <span>summaries ${result.diagnostics.summary_node_count}</span>
        <span>leaves ${result.diagnostics.leaf_node_count}</span>
        <span>support leaves ${result.diagnostics.supporting_leaf_count}</span>
        <span>retrieved tokens ${result.diagnostics.retrieved_token_count}</span>
        <span>packed tokens ${result.diagnostics.packed_token_count}</span>
        <span>branches ${result.diagnostics.branch_count}</span>
        <span>fallback ${result.diagnostics.fallback_used ? "yes" : "no"}</span>
      </div>
      <div class="packed-context">${result.packed_context}</div>
    </div>
    <div class="detail-card">
      <strong>Retrieved nodes</strong>
      ${result.retrieved_nodes
        .map(
          (item) => `
            <div class="tree-node">
              <div class="timeline-meta">
                ${badge(item.node.level)}
                ${badge(item.selected_as || "selected")}
              </div>
              <p>${item.node.text}</p>
              <div class="score-row muted">
                <span>score ${item.score.toFixed(3)}</span>
                <span>rel ${Number(item.relevance_score || 0).toFixed(3)}</span>
                <span>rec ${Number(item.recency_score || 0).toFixed(3)}</span>
                <span>imp ${Number(item.importance_score || 0).toFixed(3)}</span>
              </div>
              <p class="muted">${item.selection_reason || ""}</p>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderRetrievalTraces(traces) {
  retrievalTracesEl.innerHTML = traces.length
    ? traces
        .map(
          (trace) => `
            <article class="trace-card">
              <div class="trace-meta">
                ${badge(trace.mode)}
                ${badge(`depth ${trace.retrieval_depth}`)}
                ${badge(`branches ${trace.diagnostics.branch_count}`)}
              </div>
              <strong>${trace.query}</strong>
              <p class="muted">${new Date(trace.created_at).toLocaleString()}</p>
              <div class="score-row muted">
                <span>nodes ${trace.diagnostics.retrieved_node_count}</span>
                <span>summaries ${trace.diagnostics.summary_node_count}</span>
                <span>support leaves ${trace.diagnostics.supporting_leaf_count}</span>
                <span>retrieved tokens ${trace.diagnostics.retrieved_token_count}</span>
                <span>avg score ${Number(trace.diagnostics.avg_score || 0).toFixed(3)}</span>
                <span>fallback ${trace.diagnostics.fallback_used ? "yes" : "no"}</span>
              </div>
              <ul>
                ${trace.entries
                  .map(
                    (entry) =>
                      `<li>${entry.selected_as}: ${entry.node_type} ${entry.node_id.slice(0, 8)} • ${entry.selection_reason}</li>`,
                  )
                  .join("")}
              </ul>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">No retrieval traces yet.</div>`;
}

function renderModelTraces(traces) {
  modelTracesEl.innerHTML = traces.length
    ? traces
        .map(
          (trace) => `
            <article class="trace-card">
              <div class="trace-meta">
                ${badge(trace.component)}
                ${badge(trace.provider)}
              </div>
              <strong>${trace.model_name}</strong>
              <p class="muted">${new Date(trace.created_at).toLocaleString()}</p>
              <p class="muted">Prompt version: ${trace.prompt_version || "n/a"}</p>
              <p class="muted">Node: ${trace.node_id ? trace.node_id.slice(0, 8) : "n/a"}</p>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">No model traces yet.</div>`;
}

function metricValue(metrics, name) {
  return metrics.find((metric) => metric.name === name)?.value ?? 0;
}

function renderEvalRuns(runs) {
  evalRunsEl.innerHTML = runs.length
    ? runs
        .map(
          (run) => `
            <article class="eval-card">
              <div class="eval-meta">
                ${badge(run.scenario_name)}
              </div>
              <strong>Hierarchy vs flat recall</strong>
              <p>${metricValue(run.hierarchy_metrics, "keyword_recall").toFixed(2)} vs ${metricValue(run.baseline_metrics, "keyword_recall").toFixed(2)}</p>
              <div class="score-row muted">
                <span>hier depth ${metricValue(run.hierarchy_metrics, "retrieval_depth").toFixed(0)}</span>
                <span>flat depth ${metricValue(run.baseline_metrics, "retrieval_depth").toFixed(0)}</span>
                <span>token gain ${metricValue(run.hierarchy_metrics, "token_efficiency_gain").toFixed(0)}</span>
                <span>summaries ${metricValue(run.hierarchy_metrics, "summary_count").toFixed(0)}</span>
                <span>branches ${metricValue(run.hierarchy_metrics, "branch_count").toFixed(0)}</span>
              </div>
              <p class="muted">${(run.notes || []).join(" ")}</p>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-state">No eval runs yet.</div>`;
}

async function loadTimeline() {
  const timeline = await fetchJson(`/v1/agents/${encodeURIComponent(state.agentId)}/timeline`);
  renderTimeline(timeline.nodes);
}

async function loadTree() {
  const tree = await fetchJson(`/v1/agents/${encodeURIComponent(state.agentId)}/tree`);
  renderTree(tree);
}

async function loadTraces() {
  const [retrievals, modelTraces] = await Promise.all([
    fetchJson(`/v1/retrievals?agent_id=${encodeURIComponent(state.agentId)}&limit=10`),
    fetchJson(`/v1/model-traces?agent_id=${encodeURIComponent(state.agentId)}&limit=10`),
  ]);
  renderRetrievalTraces(retrievals);
  renderModelTraces(modelTraces);
}

async function loadEvalRuns() {
  const runs = await fetchJson("/v1/evals/runs");
  renderEvalRuns(runs);
}

async function selectNode(nodeId) {
  state.selectedNodeId = nodeId;
  const provenance = await fetchJson(`/v1/nodes/${encodeURIComponent(nodeId)}/provenance`);
  renderNodeDetail(provenance);
}

async function runRetrieval(event) {
  event.preventDefault();
  const query = document.getElementById("query").value;
  const mode = document.getElementById("mode").value;
  const tokenBudget = Number(document.getElementById("token-budget").value);
  const result = await fetchJson("/v1/memories/retrieve", {
    method: "POST",
    body: JSON.stringify({
      agent_id: state.agentId,
      query,
      query_time: new Date().toISOString(),
      mode,
      token_budget: tokenBudget,
      branch_limit: 3,
    }),
  });
  renderRetrievalResult(result);
  await loadTraces();
}

async function runEvals() {
  await fetchJson("/v1/evals/run", {
    method: "POST",
    body: JSON.stringify({ agent_id: state.agentId }),
  });
  await loadEvalRuns();
}

async function loadAgent(agentId) {
  state.agentId = agentId;
  await Promise.all([loadTimeline(), loadTree(), loadTraces(), loadEvalRuns()]);
  retrievalResultEl.innerHTML = `<div class="empty-state">Run a retrieval to inspect packed context and branch choices.</div>`;
  nodeDetailEl.innerHTML = `<div class="empty-state">Select a timeline item to inspect provenance and children.</div>`;
}

document.getElementById("agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadAgent(document.getElementById("agent-id").value.trim());
});

document.getElementById("refresh-timeline").addEventListener("click", () => loadAgent(state.agentId));
document.getElementById("retrieve-form").addEventListener("submit", runRetrieval);
document.getElementById("run-evals").addEventListener("click", runEvals);

loadAgent(state.agentId).catch((error) => {
  timelineEl.innerHTML = `<div class="empty-state">Failed to load inspector: ${error.message}</div>`;
});
