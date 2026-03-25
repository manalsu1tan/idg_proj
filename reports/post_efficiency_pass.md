# Benchmark Report

Generated: 2026-03-23T09:46:14.658664+00:00
Source: stored_eval_runs

## Summary

- Scenarios: 5
- Hierarchy recall wins: 3
- Recall ties: 1
- Average keyword recall: baseline 0.733, hierarchy 0.833
- Average recall gain: 0.100
- Average retrieved tokens: baseline 13.4, hierarchy 18.0
- Average retrieved token delta: -4.6

## Scenario Results

| Scenario | Baseline Recall | Hierarchy Recall | Recall Gain | Baseline Tokens | Hierarchy Tokens | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| delayed_commitment | 0.750 | 1.000 | 0.250 | 15.0 | 14.0 | 1.0 |
| routine_interruption | 1.000 | 0.667 | -0.333 | 16.0 | 12.0 | 4.0 |
| relationship_context | 0.500 | 0.500 | 0.000 | 13.0 | 16.0 | -3.0 |
| commitment_revision | 0.667 | 1.000 | 0.333 | 12.0 | 23.0 | -11.0 |
| identity_shift | 0.750 | 1.000 | 0.250 | 11.0 | 25.0 | -14.0 |

## Notes

- `delayed_commitment`: Long-horizon recall after many irrelevant routines.
- `routine_interruption`: Rare pivotal event should survive routine repetition.
- `relationship_context`: Relationship context should remain recoverable as actionable guidance.
- `commitment_revision`: Later corrective evidence should dominate outdated commitments.
- `identity_shift`: The system should favor the updated self-model over obsolete self-description.
