# Benchmark Report

Generated: 2026-03-23T10:40:09.935311+00:00
Source: stored_eval_runs

## Summary

- Scenarios: 5
- Hierarchy recall wins: 0
- Recall ties: 5
- Average keyword recall: baseline 0.733, hierarchy 0.733
- Average recall gain: 0.000
- Average retrieved tokens: baseline 13.4, hierarchy 14.6
- Average retrieved token delta: -1.2

## Scenario Results

| Scenario | Baseline Recall | Hierarchy Recall | Recall Gain | Baseline Tokens | Hierarchy Tokens | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| delayed_commitment | 0.750 | 0.750 | 0.000 | 15.0 | 15.0 | 0.0 |
| routine_interruption | 1.000 | 1.000 | 0.000 | 16.0 | 16.0 | 0.0 |
| relationship_context | 0.500 | 0.500 | 0.000 | 13.0 | 16.0 | -3.0 |
| commitment_revision | 0.667 | 0.667 | 0.000 | 12.0 | 12.0 | 0.0 |
| identity_shift | 0.750 | 0.750 | 0.000 | 11.0 | 14.0 | -3.0 |

## Notes

- `delayed_commitment`: Long-horizon recall after many irrelevant routines.
- `routine_interruption`: Rare pivotal event should survive routine repetition.
- `relationship_context`: Relationship context should remain recoverable as actionable guidance.
- `commitment_revision`: Later corrective evidence should dominate outdated commitments.
- `identity_shift`: The system should favor the updated self-model over obsolete self-description.
