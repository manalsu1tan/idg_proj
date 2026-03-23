# Benchmark Report

Generated: 2026-03-23T07:47:06.799022+00:00
Source: stored_eval_runs

## Summary

- Scenarios: 5
- Hierarchy recall wins: 3
- Recall ties: 2
- Average keyword recall: baseline 0.733, hierarchy 0.950
- Average recall gain: 0.217
- Average retrieved tokens: baseline 13.4, hierarchy 35.4
- Average retrieved token delta: -22.0

## Scenario Results

| Scenario | Baseline Recall | Hierarchy Recall | Recall Gain | Baseline Tokens | Hierarchy Tokens | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| delayed_commitment | 0.750 | 1.000 | 0.250 | 15.0 | 33.0 | -18.0 |
| routine_interruption | 1.000 | 1.000 | 0.000 | 16.0 | 28.0 | -12.0 |
| relationship_context | 0.500 | 1.000 | 0.500 | 13.0 | 44.0 | -31.0 |
| commitment_revision | 0.667 | 1.000 | 0.333 | 12.0 | 30.0 | -18.0 |
| identity_shift | 0.750 | 0.750 | 0.000 | 11.0 | 42.0 | -31.0 |

## Notes

- `delayed_commitment`: Long-horizon recall after many irrelevant routines.
- `routine_interruption`: Rare pivotal event should survive routine repetition.
- `relationship_context`: Relationship context should remain recoverable as actionable guidance.
- `commitment_revision`: Later corrective evidence should dominate outdated commitments.
- `identity_shift`: The system should favor the updated self-model over obsolete self-description.
