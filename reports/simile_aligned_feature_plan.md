# Dissertation-Faithful Feature Plan

This plan turns the three shortlisted additions into concrete implementation work that stays aligned with the generative-agents / dissertation lineage.

Design principle:
- do not bolt on enterprise features
- extend the current system along its native axes: memory grounding, counterfactual simulation, and legible social-state observability
- keep each feature independently shippable and demoable
- emphasize production-level quality standards

Current repo anchors:
- API and request/response surface: [apps/api/main.py](/Users/Manal/Documents/GitHub/idg_proj/apps/api/main.py:465)
- shared schemas: [packages/schemas/models.py](/Users/Manal/Documents/GitHub/idg_proj/packages/schemas/models.py:76)
- memory orchestration: [packages/memory_core/services.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/services.py:66)
- persistence: [packages/memory_core/storage.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/storage.py:172)
- eval harness: [packages/evals/runner.py](/Users/Manal/Documents/GitHub/idg_proj/packages/evals/runner.py:66)
- scenario catalog: [packages/evals/scenarios.py](/Users/Manal/Documents/GitHub/idg_proj/packages/evals/scenarios.py:21)
- inspector UI: [apps/ui/static/index.html](/Users/Manal/Documents/GitHub/idg_proj/apps/ui/static/index.html:11), [apps/ui/static/app.js](/Users/Manal/Documents/GitHub/idg_proj/apps/ui/static/app.js:1)

## Feature 1: Event Log Ingestion

Goal:
Add a generic grounding path that imports external experience logs into the memory hierarchy. The input should stay domain-neutral: observation streams, transcripts, world events, diary-like logs, or small-society simulation events.

Why this matters:
- faithful to the dissertation's memory stream and environment-conditioning story
- demonstrates data lifecycle ownership without introducing a business wrapper
- gives the project a concrete "external data to agent memory" path

Effort:
- 1.5 to 2.5 days

### API shape

New endpoint:
- `POST /v1/memories/ingest/batch`

Schema additions in [packages/schemas/models.py](/Users/Manal/Documents/GitHub/idg_proj/packages/schemas/models.py:76):

```json
{
  "agent_id": "demo-agent-1",
  "records": [
    {
      "text": "Sasha said she wants the final talking points in writing.",
      "timestamp": "2025-02-07T09:30:00Z",
      "importance_score": 0.92,
      "node_type": "episode",
      "entities": ["Sasha"],
      "topics": ["workshop", "messaging"],
      "source_type": "transcript",
      "source_id": "meeting-2025-02-07",
      "event_id": "meeting-2025-02-07-line-18",
      "allow_duplicate": false
    }
  ],
  "sort_by_timestamp": true,
  "build_summaries_after_ingest": false
}
```

Suggested response:

```json
{
  "agent_id": "demo-agent-1",
  "received_count": 1,
  "ingested_count": 1,
  "duplicate_count": 0,
  "built_summary_count": 0,
  "node_ids": ["..."],
  "duplicates": []
}
```

### Schema work

Update [packages/schemas/models.py](/Users/Manal/Documents/GitHub/idg_proj/packages/schemas/models.py:76):
- add `MemorySourceMetadata`
- add optional source fields onto `MemoryNode`
  - `source_type: str | None`
  - `source_id: str | None`
  - `event_id: str | None`
- add `IngestMemoryRecord`
- add `BatchIngestMemoriesRequest`
- add `BatchIngestMemoriesResponse`

### Storage work

Update [packages/memory_core/storage.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/storage.py:172):
- persist the new source metadata fields on `NodeRecord`
- map those fields in `_to_node(...)` and `upsert_node(...)`
- add `find_existing_l0_by_event_id(agent_id, event_id)` for idempotent ingest
- add `write_l0_batch(...)` convenience method if you want dedupe and normalization close to persistence

Likely migration:
- add new nullable columns to `memory_nodes`
  - `source_type`
  - `source_id`
  - `event_id`

New migration file:
- `alembic/versions/<timestamp>_000005_memory_source_metadata.py`

### Service work

Update [packages/memory_core/services.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/services.py:66):
- add `ingest_batch(...)`
- normalize timestamps
- optionally sort by timestamp before insert
- skip duplicates when `event_id` already exists and `allow_duplicate=false`
- optionally call `build_summaries(...)` after ingest

### API work

Update [apps/api/main.py](/Users/Manal/Documents/GitHub/idg_proj/apps/api/main.py:465):
- keep `POST /v1/memories/ingest` as the single-record primitive
- add `POST /v1/memories/ingest/batch`

Optional demo payloads:
- add a small event-log fixture under `packages/evals/` or `tests/fixtures/`

### Tests

Add or extend:
- [tests/test_memory_system.py](/Users/Manal/Documents/GitHub/idg_proj/tests/test_memory_system.py:23)
- `tests/test_batch_ingest.py` if you want a dedicated file

Test cases:
- preserves timestamp ordering
- skips duplicate `event_id` records
- allows duplicates when explicitly requested
- persists provenance metadata
- optional summary build after ingest works

### Deliverable

Minimum shippable output:
- one batch ingest endpoint
- one migration
- one short fixture showing transcript/world-event import
- tests covering dedupe and provenance

## Feature 2: Counterfactual Replay

Goal:
Run a base scenario and one or more minimally edited variants, then compare how changes in memory alter retrieval, summaries, and downstream answers.

Why this matters:
- strongest dissertation-faithful signal that the project is about simulation, not only retrieval benchmarking
- maps naturally to "translate uncertainty into simulation parameters"
- gives the report a compelling narrative: changing one event changes downstream behavior

Effort:
- 2 to 3 days

### API shape

New endpoint:
- `POST /v1/evals/counterfactual/run`

Suggested request:

```json
{
  "scenario_name": "relationship_context",
  "seed": 11,
  "variants": [
    {
      "variant_id": "sasha_no_written_prep",
      "description": "Remove the written follow-up signal and replace it with a casual sync preference.",
      "operations": [
        {
          "op": "replace_event_text",
          "match_text": "Reflected that communication with Sasha works best when expectations are sent in writing ahead of time.",
          "new_text": "Reflected that communication with Sasha works best as a quick live sync right before the meeting."
        }
      ]
    }
  ],
  "query_override": "How should I communicate with Sasha?",
  "token_budget": 120,
  "mode": "balanced"
}
```

Suggested response:

```json
{
  "report_type": "counterfactual_replay_report",
  "scenario_name": "relationship_context__seed_11",
  "query": "How should I communicate with Sasha?",
  "base": {
    "retrieval_depth": 2,
    "packed_context": "...",
    "retrieved_node_ids": ["..."],
    "answer": {
      "text": "...",
      "confidence": 0.82
    }
  },
  "variants": [
    {
      "variant_id": "sasha_no_written_prep",
      "description": "...",
      "retrieval_depth": 1,
      "packed_context": "...",
      "retrieved_node_ids": ["..."],
      "answer": {
        "text": "...",
        "confidence": 0.74
      },
      "diff": {
        "answer_changed": true,
        "retrieval_depth_delta": -1,
        "retrieved_token_delta": -18,
        "added_node_ids": ["..."],
        "removed_node_ids": ["..."]
      }
    }
  ]
}
```

### New module

Add:
- `packages/evals/counterfactual.py`

Responsibilities:
- load a base `Scenario`
- apply variant operations
- run base and variant with fresh `MemoryService` instances
- compare:
  - retrieved node IDs
  - retrieval depth
  - token count
  - summary count
  - packed context
  - answer text and confidence
- export structured payload + markdown

### Schema work

Update [packages/schemas/models.py](/Users/Manal/Documents/GitHub/idg_proj/packages/schemas/models.py:214):
- add `CounterfactualOperation`
- add `CounterfactualVariantRequest`
- add `CounterfactualReplayRequest`
- optionally add typed response models if you want first-class API docs

Recommended operation types:
- `replace_event_text`
- `remove_event`
- `insert_event_after_day`
- `change_importance`

### Report/export work

Add support for markdown export in:
- new `packages/evals/counterfactual.py`

Optional script:
- `scripts/export_counterfactual_report.sh`

Optional artifact output:
- `reports/counterfactual_<timestamp>.json`
- `reports/counterfactual_<timestamp>.md`

### API work

Update [apps/api/main.py](/Users/Manal/Documents/GitHub/idg_proj/apps/api/main.py:522):
- add `POST /v1/evals/counterfactual/run`
- optionally add `GET /v1/evals/counterfactual/report.md` only if you want parity with the existing reporting pattern

### Tests

Add:
- `tests/test_counterfactual.py`

Test cases:
- variant operation application is deterministic
- base and variant run on isolated services
- response includes retrieval and answer deltas
- at least one variant measurably changes output

### Deliverable

Minimum shippable output:
- one new counterfactual evaluator module
- one API endpoint
- one markdown report renderer
- one demo based on `relationship_context` or `commitment_revision`

## Feature 3: Social State Digest

Goal:
Expose a legible "current social state" summary for one agent or a small society. This is not an executive dashboard. It is an observability layer over memory, reflection, and likely next action.

Why this matters:
- keeps the project in the interactive-systems / believable-agents lane
- makes the memory hierarchy understandable to anyone reviewing the repo
- improves demo quality without changing project identity

Effort:
- 1.5 to 2 days

### API shape

New endpoint:
- `GET /v1/agents/{agent_id}/social-state`

Suggested response:

```json
{
  "agent_id": "demo-agent-stakeholder-handoff",
  "snapshot_at": "2025-02-08T09:00:00Z",
  "active_commitments": [
    {
      "text": "Present the narrated walkthrough instead of the interactive prototype.",
      "support_node_ids": ["..."]
    }
  ],
  "active_revisions": [
    {
      "text": "The deliverable changed from prototype to narrated walkthrough.",
      "support_node_ids": ["..."]
    }
  ],
  "relationship_guidance": [
    {
      "entity": "Sasha",
      "guidance": "Send written expectations and final talking points ahead of time.",
      "support_node_ids": ["..."]
    }
  ],
  "open_tensions": [
    {
      "label": "AV risk",
      "description": "Projector instability requires backup equipment and local file fallback.",
      "support_node_ids": ["..."]
    }
  ],
  "likely_next_actions": [
    {
      "text": "Send Sasha the final talking points in writing.",
      "confidence": 0.75
    }
  ],
  "stale_summary_count": 0
}
```

### New module

Add:
- `packages/memory_core/social_state.py`

Responsibilities:
- derive digest fields from current L0/L1/L2 nodes
- prioritize structured summary fields already present on `MemoryNode`
  - `commitments`
  - `revisions`
  - `preferences`
  - `relationship_guidance`
- fall back to heuristics over recent nodes when structured fields are sparse
- emit provenance through supporting node IDs

### Schema work

Update [packages/schemas/models.py](/Users/Manal/Documents/GitHub/idg_proj/packages/schemas/models.py:259):
- add `DigestEvidenceItem`
- add `SocialStateItem`
- add `SocialStateDigestResponse`

### Service work

Update [packages/memory_core/services.py](/Users/Manal/Documents/GitHub/idg_proj/packages/memory_core/services.py:66):
- add `social_state(agent_id: str) -> SocialStateDigestResponse`
- source data from current non-stale nodes

### API work

Update [apps/api/main.py](/Users/Manal/Documents/GitHub/idg_proj/apps/api/main.py:593):
- add `GET /v1/agents/{agent_id}/social-state`

### UI work

Update:
- [apps/ui/static/index.html](/Users/Manal/Documents/GitHub/idg_proj/apps/ui/static/index.html:39)
- [apps/ui/static/app.js](/Users/Manal/Documents/GitHub/idg_proj/apps/ui/static/app.js:1)
- [apps/ui/static/styles.css](/Users/Manal/Documents/GitHub/idg_proj/apps/ui/static/styles.css:1)

Suggested UI addition:
- new top-level panel above or beside the existing inspector
- sections:
  - active commitments
  - revisions
  - relationship guidance
  - tensions / risks
  - likely next actions

The UI should remain read-only and provenance-first.

### Tests

Add:
- `tests/test_social_state.py`

Test cases:
- digest extracts commitments and revisions from seeded demo
- relationship guidance includes entity-aware evidence
- stale summaries are excluded

### Deliverable

Minimum shippable output:
- one derived digest endpoint
- one UI panel that renders the digest
- tests against the stakeholder-handoff demo

## Recommended Order Of Commits

This order keeps the work incremental and report-friendly.

### Commit 1: Batch Event Log Ingestion

Message:
- `Add batch event-log ingestion with provenance metadata`

Files:
- `packages/schemas/models.py`
- `packages/memory_core/storage.py`
- `packages/memory_core/services.py`
- `apps/api/main.py`
- `alembic/versions/<timestamp>_000005_memory_source_metadata.py`
- `tests/test_batch_ingest.py` or `tests/test_memory_system.py`

Why first:
- lowest conceptual risk
- unlocks better demos and future replay fixtures
- gives you the grounding / data lifecycle story immediately

### Commit 2: Counterfactual Replay

Message:
- `Add counterfactual replay evaluation and report export`

Files:
- `packages/schemas/models.py`
- `packages/evals/counterfactual.py`
- `apps/api/main.py`
- `scripts/export_counterfactual_report.sh` if added
- `tests/test_counterfactual.py`

Why second:
- strongest simulation signal
- easiest feature to highlight in the final report
- mostly isolated from UI work

### Commit 3: Social State Digest

Message:
- `Add social-state digest API and inspector panel`

Files:
- `packages/schemas/models.py`
- `packages/memory_core/social_state.py`
- `packages/memory_core/services.py`
- `apps/api/main.py`
- `apps/ui/static/index.html`
- `apps/ui/static/app.js`
- `apps/ui/static/styles.css`
- `tests/test_social_state.py`

Why third:
- best polish layer after the substrate and simulation pieces exist
- easiest to demo once the data and replay features are in place

## Recommended Report Framing

After these three features land, the project can be described as:

`A memory-grounded generative agent substrate for long-horizon social simulation, with external experience ingestion, counterfactual replay, and provenance-first social-state observability.`

That phrasing stays faithful to the dissertation lineage while making the Simile-relevant strengths easy to read:
- agent architecture
- grounding pipeline
- evaluation discipline
- simulation parameterization
- user-facing interpretability

## Time Budget

Estimated total:
- 5 to 7.5 days

Reasonable pacing:
- Day 1-2: batch ingestion
- Day 3-5: counterfactual replay
- Day 6-7: social-state digest and UI

## Cut Line If Time Runs Short

If only two features fit before the report:
1. batch ingestion
2. counterfactual replay

If only one feature fits:
1. counterfactual replay

That single feature contributes the strongest new sentence to the project narrative.
