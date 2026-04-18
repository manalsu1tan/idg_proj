const state = {
  agentId: "demo-agent-stakeholder-handoff",
  selectedNodeId: null,
  demoQueryPresets: [],
};
const DEFAULT_DEMO_SCENARIO_NAME = "stakeholder_handoff_demo_v1";
const DEFAULT_DEMO_QUERY_PRESETS = [
  {
    label: "Sasha vs. Leah",
    query: "How should I approach Sasha differently from Leah?",
  },
  {
    label: "Current deliverable",
    query: "What am I actually presenting now: the prototype or something else?",
  },
  {
    label: "AV owner and risk",
    query: "Who owns AV setup, and what risk should I prepare for?",
  },
  {
    label: "Sasha pre-read",
    query: "What should I send Sasha before the workshop?",
  },
  {
    label: "Avoid with Sasha",
    query: "What should I avoid doing with Sasha on the day of the workshop?",
  },
  {
    label: "Highest-risk gap",
    query: "If I only have time for one prep task this morning, what is the highest-risk gap?",
  },
  {
    label: "Evidence for Sasha",
    query: "Which memories support the recommendation for Sasha?",
  },
];

const timelineEl = document.getElementById("timeline");
const treeViewEl = document.getElementById("tree-view");
const nodeDetailEl = document.getElementById("node-detail");
const answerResultEl = document.getElementById("answer-result");
const retrievalResultEl = document.getElementById("retrieval-result");
const retrievalTracesEl = document.getElementById("retrieval-traces");
const modelTracesEl = document.getElementById("model-traces");
const evalRunsEl = document.getElementById("eval-runs");
const actionStatusEl = document.getElementById("action-status");
const loadAgentButtonEl = document.querySelector('#agent-form button[type="submit"]');
const buildSummariesButtonEl = document.getElementById("build-summaries");
const seedComplexDemoButtonEl = document.getElementById("seed-complex-demo");
const refreshTimelineButtonEl = document.getElementById("refresh-timeline");
const runRetrievalButtonEl = document.querySelector('#retrieve-form button[type="submit"]');
const runEvalsButtonEl = document.getElementById("run-evals");
const queryEl = document.getElementById("query");
const demoQueryPresetEl = document.getElementById("demo-query-preset");
const verifyAnswerEl = document.getElementById("verify-answer");

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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatJson(value) {
  return escapeHtml(JSON.stringify(value ?? {}, null, 2));
}

function summarizeScoreDistribution(items) {
  const scores = items
    .map((item) => Number(item?.score ?? 0))
    .filter((score) => Number.isFinite(score))
    .sort((left, right) => right - left);
  const count = scores.length;
  const top = count ? scores[0] : 0;
  const next = count > 1 ? scores[1] : null;
  const avg = count ? scores.reduce((sum, score) => sum + score, 0) / count : 0;
  const ratio = top > 0 ? avg / top : 0;
  const margin = next !== null ? top - next : null;
  return { count, top, next, avg, ratio, margin };
}

function setActionStatus(message, stateLabel = "idle") {
  if (!actionStatusEl) {
    return;
  }
  actionStatusEl.textContent = message;
  actionStatusEl.dataset.state = stateLabel;
}

function beginButtonBusy(buttonEl, busyLabel) {
  if (!buttonEl) {
    return;
  }
  if (!buttonEl.dataset.idleLabel) {
    buttonEl.dataset.idleLabel = buttonEl.textContent.trim();
  }
  buttonEl.disabled = true;
  buttonEl.classList.add("is-loading");
  buttonEl.setAttribute("aria-busy", "true");
  buttonEl.textContent = busyLabel;
}

function endButtonBusy(buttonEl) {
  if (!buttonEl) {
    return;
  }
  buttonEl.disabled = false;
  buttonEl.classList.remove("is-loading");
  buttonEl.setAttribute("aria-busy", "false");
  buttonEl.textContent = buttonEl.dataset.idleLabel || buttonEl.textContent;
}

function syncDemoQuerySelection(query) {
  if (demoQueryPresetEl) {
    demoQueryPresetEl.value = state.demoQueryPresets.some((preset) => preset.query === query) ? query : "";
  }
}

function setDemoQuery(query) {
  queryEl.value = query;
  syncDemoQuerySelection(query);
}

function renderDemoQueryPresets() {
  if (!demoQueryPresetEl) {
    return;
  }
  demoQueryPresetEl.innerHTML = [
    `<option value="">Choose a suggested query</option>`,
    ...state.demoQueryPresets.map(
      (preset, index) => `<option value="${escapeHtml(preset.query)}">Query ${index + 1}: ${escapeHtml(preset.label)}</option>`,
    ),
  ].join("");
  if (!demoQueryPresetEl.dataset.bound) {
    demoQueryPresetEl.addEventListener("change", (event) => {
      if (event.target.value) {
        setDemoQuery(event.target.value);
      }
    });
    queryEl.addEventListener("input", () => syncDemoQuerySelection(queryEl.value));
    demoQueryPresetEl.dataset.bound = "true";
  }
  syncDemoQuerySelection(queryEl.value);
}

function applyDemoConfig(payload = {}) {
  const presets = Array.isArray(payload.query_presets) && payload.query_presets.length
    ? payload.query_presets
    : DEFAULT_DEMO_QUERY_PRESETS;
  state.demoQueryPresets = presets;
  renderDemoQueryPresets();
  if (payload.agent_id) {
    state.agentId = payload.agent_id;
    document.getElementById("agent-id").value = payload.agent_id;
  }
  if (payload.query) {
    setDemoQuery(payload.query);
  } else if (!queryEl.value && presets[0]?.query) {
    setDemoQuery(presets[0].query);
  }
}

function renderTimeline(nodes) {
  const eventNodes = nodes.filter((node) => node.level === "L0");
  if (!eventNodes.length) {
    timelineEl.innerHTML = `<div class="empty-state">No event memories found for this agent.</div>`;
    return;
  }
  timelineEl.innerHTML = nodes
    .filter((node) => node.level === "L0")
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

function latestDistinct(items, keyFn) {
  const seen = new Set();
  return items.filter((item) => {
    const key = keyFn(item);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function renderTreeNode(treeNode) {
  const levelClass = `level-${String(treeNode.node.level || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")}`;
  return `
    <div class="tree-node ${levelClass}">
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
  const hierarchyWin = result.retrieval_depth > 1 && result.diagnostics.branch_count > 1 && result.diagnostics.supporting_leaf_count > 0;
  const scoreSummary = summarizeScoreDistribution(result.retrieved_nodes);
  retrievalResultEl.innerHTML = `
    <div class="detail-card">
      <div class="timeline-meta">
        ${badge(`depth ${result.retrieval_depth}`)}
        ${badge(`budget ${result.token_budget}`)}
        ${badge(result.mode)}
        ${badge(`hierarchy win ${hierarchyWin ? "yes" : "no"}`)}
      </div>
      <div class="score-row muted">
        <span>nodes ${result.diagnostics.retrieved_node_count}</span>
        <span>summaries ${result.diagnostics.summary_node_count}</span>
        <span>leaves ${result.diagnostics.leaf_node_count}</span>
        <span>support leaves ${result.diagnostics.supporting_leaf_count}</span>
        <span>retrieved tokens ${result.diagnostics.retrieved_token_count}</span>
        <span>packed tokens ${result.diagnostics.packed_token_count}</span>
        <span>branches ${result.diagnostics.branch_count}</span>
        <span>avg ranking score ${scoreSummary.avg.toFixed(3)}</span>
        <span>top score ${scoreSummary.top.toFixed(3)}</span>
        <span>avg/top ${(scoreSummary.ratio * 100).toFixed(0)}%</span>
        <span>top-next ${scoreSummary.margin === null ? "n/a" : scoreSummary.margin.toFixed(3)}</span>
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
                <span>ranking score ${item.score.toFixed(3)}</span>
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

function renderAnswerResult(result) {
  if (!result.answer) {
    answerResultEl.innerHTML = `<div class="empty-state">Run a retrieval to generate a grounded answer.</div>`;
    return;
  }
  const answer = result.answer;
  const verification = result.answer_verification;
  const issues = verification
    ? [...(verification.unsupported_claims || []), ...(verification.contradictions || []), ...(verification.omissions || [])]
    : [];
  answerResultEl.innerHTML = `
    <div class="detail-card">
      <div class="timeline-meta">
        ${badge(`confidence ${Math.round(Number(answer.confidence || 0) * 100)}%`)}
        ${badge(`${(answer.citations || []).length} citations`)}
        ${verification ? badge(verification.quality_status) : badge("verification off")}
      </div>
      <p class="answer-copy">${escapeHtml(answer.text || "")}</p>
      ${
        answer.citations?.length
          ? `<div class="timeline-meta">${answer.citations.map((citation) => badge(citation.slice(0, 8))).join("")}</div>`
          : `<p class="muted">No supporting citations were returned.</p>`
      }
    </div>
    ${
      verification
        ? `
          <div class="detail-card">
            <strong>Answer verification</strong>
            <p class="muted">Status: ${escapeHtml(verification.quality_status)}</p>
            ${
              issues.length
                ? `<ul>${issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>`
                : `<p class="muted">No unsupported claims or contradictions flagged.</p>`
            }
          </div>
        `
        : ""
    }
  `;
}

function renderRetrievalTraces(traces) {
  const distinctTraces = latestDistinct(traces, (trace) => trace.query);
  retrievalTracesEl.innerHTML = distinctTraces.length
    ? distinctTraces
        .map(
          (trace) => {
            const hierarchyWin =
              trace.retrieval_depth > 1 && trace.diagnostics.branch_count > 1 && trace.diagnostics.supporting_leaf_count > 0;
            const scoreSummary = summarizeScoreDistribution(trace.entries);
            return `
            <article class="trace-card">
              <div class="trace-meta">
                ${badge(trace.mode)}
                ${badge(`depth ${trace.retrieval_depth}`)}
                ${badge(`branches ${trace.diagnostics.branch_count}`)}
                ${badge(`hierarchy win ${hierarchyWin ? "yes" : "no"}`)}
              </div>
              <strong>${trace.query}</strong>
              <p class="muted">${new Date(trace.created_at).toLocaleString()}</p>
              <div class="score-row muted">
                <span>nodes ${trace.diagnostics.retrieved_node_count}</span>
                <span>summaries ${trace.diagnostics.summary_node_count}</span>
                <span>support leaves ${trace.diagnostics.supporting_leaf_count}</span>
                <span>retrieved tokens ${trace.diagnostics.retrieved_token_count}</span>
                <span>avg ranking score ${scoreSummary.avg.toFixed(3)}</span>
                <span>top score ${scoreSummary.top.toFixed(3)}</span>
                <span>avg/top ${(scoreSummary.ratio * 100).toFixed(0)}%</span>
                <span>top-next ${scoreSummary.margin === null ? "n/a" : scoreSummary.margin.toFixed(3)}</span>
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
          `;
          },
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
              <details>
                <summary>Inspect request and response</summary>
                <p class="trace-section-label">Request</p>
                <pre class="trace-payload">${formatJson(trace.request_payload)}</pre>
                <p class="trace-section-label">Response</p>
                <pre class="trace-payload">${formatJson(trace.response_payload)}</pre>
              </details>
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
  const distinctRuns = latestDistinct(runs, (run) => run.scenario_name);
  evalRunsEl.innerHTML = distinctRuns.length
    ? distinctRuns
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
  beginButtonBusy(runRetrievalButtonEl, "Running retrieval...");
  setActionStatus("Running retrieval...", "running");
  try {
    const query = queryEl.value;
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
        generate_answer: true,
        verify_answer: Boolean(verifyAnswerEl?.checked),
      }),
    });
    renderAnswerResult(result);
    renderRetrievalResult(result);
    await loadTraces();
    setActionStatus("Retrieval complete", "idle");
  } catch (error) {
    setActionStatus(`Retrieval failed: ${error.message}`, "error");
    throw error;
  } finally {
    endButtonBusy(runRetrievalButtonEl);
  }
}

async function runEvals() {
  beginButtonBusy(runEvalsButtonEl, "Running evals...");
  setActionStatus("Running evals...", "running");
  try {
    await fetchJson("/v1/evals/run", {
      method: "POST",
      body: JSON.stringify({ agent_id: state.agentId }),
    });
    await loadEvalRuns();
    setActionStatus("Eval run complete", "idle");
  } catch (error) {
    setActionStatus(`Eval run failed: ${error.message}`, "error");
    throw error;
  } finally {
    endButtonBusy(runEvalsButtonEl);
  }
}

async function buildSummaries() {
  beginButtonBusy(buildSummariesButtonEl, "Building...");
  setActionStatus("Building summaries...", "running");
  try {
    const built = await fetchJson("/v1/summaries/build", {
      method: "POST",
      body: JSON.stringify({
        agent_id: state.agentId,
        query_time: new Date().toISOString(),
      }),
    });
    await Promise.all([loadTimeline(), loadTree(), loadTraces()]);
    setActionStatus(`Built ${built.length} summaries`, "idle");
  } catch (error) {
    setActionStatus(`Summary build failed: ${error.message}`, "error");
    throw error;
  } finally {
    endButtonBusy(buildSummariesButtonEl);
  }
}

async function loadAgent(agentId) {
  state.agentId = agentId;
  beginButtonBusy(loadAgentButtonEl, "Loading agent...");
  setActionStatus("Loading agent data...", "running");
  try {
    await Promise.all([loadTimeline(), loadTree(), loadTraces(), loadEvalRuns()]);
    answerResultEl.innerHTML = `<div class="empty-state">Run a retrieval to generate a grounded answer.</div>`;
    retrievalResultEl.innerHTML = `<div class="empty-state">Run a retrieval to inspect packed context and branch choices.</div>`;
    nodeDetailEl.innerHTML = `<div class="empty-state">Select a timeline item to inspect provenance and children.</div>`;
    setActionStatus("Agent loaded", "idle");
  } catch (error) {
    setActionStatus(`Load failed: ${error.message}`, "error");
    throw error;
  } finally {
    endButtonBusy(loadAgentButtonEl);
  }
}

async function seedComplexDemo() {
  beginButtonBusy(seedComplexDemoButtonEl, "Seeding demo...");
  setActionStatus("Seeding demo scenario...", "running");
  try {
    const seedResult = await fetchJson("/v1/demo/seed-complex", {
      method: "POST",
      body: JSON.stringify({
        scenario_name: DEFAULT_DEMO_SCENARIO_NAME,
        force: true,
      }),
    });
    applyDemoConfig(seedResult);
    await loadAgent(seedResult.agent_id);
    setActionStatus(
      `Demo scenario seeded (${seedResult.l0_count} L0, ${seedResult.l1_count} L1, ${seedResult.l2_count} L2)`,
      "idle",
    );
  } catch (error) {
    setActionStatus(`Seeding failed: ${error.message}`, "error");
    throw error;
  } finally {
    endButtonBusy(seedComplexDemoButtonEl);
  }
}

async function initializeDemo() {
  try {
    const seedResult = await fetchJson("/v1/demo/seed-complex", {
      method: "POST",
      body: JSON.stringify({
        scenario_name: DEFAULT_DEMO_SCENARIO_NAME,
        force: false,
      }),
    });
    applyDemoConfig(seedResult);
    await loadAgent(seedResult.agent_id);
    if (seedResult.seeded) {
      setActionStatus(
        `Demo scenario seeded (${seedResult.l0_count} L0, ${seedResult.l1_count} L1, ${seedResult.l2_count} L2)`,
        "idle",
      );
    }
  } catch (error) {
    setActionStatus(`Failed to initialize demo: ${error.message}`, "error");
    timelineEl.innerHTML = `<div class="empty-state">Failed to initialize demo: ${error.message}</div>`;
  }
}

document.getElementById("agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadAgent(document.getElementById("agent-id").value.trim());
});

document.getElementById("refresh-timeline").addEventListener("click", async () => {
  beginButtonBusy(refreshTimelineButtonEl, "Refreshing...");
  setActionStatus("Refreshing timeline...", "running");
  try {
    await loadAgent(state.agentId);
    setActionStatus("Timeline refreshed", "idle");
  } catch (error) {
    setActionStatus(`Refresh failed: ${error.message}`, "error");
    throw error;
  } finally {
    endButtonBusy(refreshTimelineButtonEl);
  }
});
document.getElementById("retrieve-form").addEventListener("submit", runRetrieval);
document.getElementById("run-evals").addEventListener("click", runEvals);
document.getElementById("build-summaries").addEventListener("click", buildSummaries);
document.getElementById("seed-complex-demo").addEventListener("click", seedComplexDemo);
applyDemoConfig({ agent_id: state.agentId, query_presets: DEFAULT_DEMO_QUERY_PRESETS, query: DEFAULT_DEMO_QUERY_PRESETS[0].query });
initializeDemo();
