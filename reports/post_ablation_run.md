# Benchmark Ablation Report

Generated: 2026-03-24T04:08:19.330697+00:00

## Winner Counts

- `flat_baseline`: 4
- `hierarchy_summary_only`: 1
- `hierarchy_balanced`: 0
- `hierarchy_drill_down`: 0
- `hierarchy_top_leaf_only`: 0

## Scenario Winners

| Scenario | Best Mode | |
| --- | --- | --- |
| delayed_commitment | flat_baseline | |
| routine_interruption | flat_baseline | |
| relationship_context | flat_baseline | |
| commitment_revision | hierarchy_summary_only | |
| identity_shift | flat_baseline | |

## Per-Scenario Details

### delayed_commitment

- Best mode: `flat_baseline`
- Notes: Long-horizon recall after many irrelevant routines.

| Mode | Recall | Recall/Token | Tokens | Depth | Nodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| flat_baseline | 0.750 | 0.050 | 15.0 | 1.0 | 1.0 |
| hierarchy_summary_only | 0.500 | 0.015 | 34.0 | 1.0 | 3.0 |
| hierarchy_balanced | 0.500 | 0.015 | 34.0 | 1.0 | 3.0 |
| hierarchy_drill_down | 0.500 | 0.021 | 24.0 | 2.0 | 2.0 |
| hierarchy_top_leaf_only | 0.500 | 0.042 | 12.0 | 2.0 | 1.0 |

### routine_interruption

- Best mode: `flat_baseline`
- Notes: Rare pivotal event should survive routine repetition.

| Mode | Recall | Recall/Token | Tokens | Depth | Nodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| flat_baseline | 1.000 | 0.062 | 16.0 | 1.0 | 1.0 |
| hierarchy_summary_only | 0.667 | 0.026 | 26.0 | 1.0 | 3.0 |
| hierarchy_balanced | 1.000 | 0.036 | 28.0 | 2.0 | 3.0 |
| hierarchy_drill_down | 1.000 | 0.031 | 32.0 | 2.0 | 2.0 |
| hierarchy_top_leaf_only | 1.000 | 0.062 | 16.0 | 2.0 | 1.0 |

### relationship_context

- Best mode: `flat_baseline`
- Notes: Relationship context should remain recoverable as actionable guidance.

| Mode | Recall | Recall/Token | Tokens | Depth | Nodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| flat_baseline | 0.500 | 0.038 | 13.0 | 1.0 | 1.0 |
| hierarchy_summary_only | 0.250 | 0.023 | 11.0 | 1.0 | 1.0 |
| hierarchy_balanced | 0.250 | 0.023 | 11.0 | 2.0 | 1.0 |
| hierarchy_drill_down | 0.250 | 0.011 | 22.0 | 2.0 | 2.0 |
| hierarchy_top_leaf_only | 0.250 | 0.023 | 11.0 | 2.0 | 1.0 |

### commitment_revision

- Best mode: `hierarchy_summary_only`
- Notes: Later corrective evidence should dominate outdated commitments.

| Mode | Recall | Recall/Token | Tokens | Depth | Nodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| flat_baseline | 0.667 | 0.056 | 12.0 | 1.0 | 1.0 |
| hierarchy_summary_only | 0.667 | 0.074 | 9.0 | 1.0 | 1.0 |
| hierarchy_balanced | 0.667 | 0.056 | 12.0 | 2.0 | 1.0 |
| hierarchy_drill_down | 0.667 | 0.028 | 24.0 | 2.0 | 2.0 |
| hierarchy_top_leaf_only | 0.667 | 0.056 | 12.0 | 2.0 | 1.0 |

### identity_shift

- Best mode: `flat_baseline`
- Notes: The system should favor the updated self-model over obsolete self-description.

| Mode | Recall | Recall/Token | Tokens | Depth | Nodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| flat_baseline | 0.750 | 0.068 | 11.0 | 1.0 | 1.0 |
| hierarchy_summary_only | 0.750 | 0.054 | 14.0 | 1.0 | 1.0 |
| hierarchy_balanced | 0.750 | 0.054 | 14.0 | 2.0 | 1.0 |
| hierarchy_drill_down | 0.750 | 0.027 | 28.0 | 2.0 | 2.0 |
| hierarchy_top_leaf_only | 0.750 | 0.054 | 14.0 | 2.0 | 1.0 |

