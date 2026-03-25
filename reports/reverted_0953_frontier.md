# Benchmark Report

Generated: 2026-03-25T06:48:02.271046+00:00
Source: stored_eval_runs

## Summary

- Scenarios: 5
- Hierarchy recall wins: 3
- Recall ties: 2
- Average keyword recall: baseline 0.733, hierarchy 0.900
- Average recall gain: 0.167
- Average retrieved tokens: baseline 13.4, hierarchy 19.4
- Average retrieved token delta: -6.0

## Scenario Results

| Scenario | Baseline Recall | Hierarchy Recall | Recall Gain | Baseline Tokens | Hierarchy Tokens | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| delayed_commitment | 0.750 | 1.000 | 0.250 | 15.0 | 10.0 | 5.0 |
| routine_interruption | 1.000 | 1.000 | 0.000 | 16.0 | 16.0 | 0.0 |
| relationship_context | 0.500 | 0.500 | 0.000 | 13.0 | 16.0 | -3.0 |
| commitment_revision | 0.667 | 1.000 | 0.333 | 12.0 | 30.0 | -18.0 |
| identity_shift | 0.750 | 1.000 | 0.250 | 11.0 | 25.0 | -14.0 |

## Notes

- `delayed_commitment`: Long-horizon recall after many irrelevant routines.
- `routine_interruption`: Rare pivotal event should survive routine repetition.
- `relationship_context`: Relationship context should remain recoverable as actionable guidance.
- `commitment_revision`: Later corrective evidence should dominate outdated commitments.
- `identity_shift`: The system should favor the updated self-model over obsolete self-description.
