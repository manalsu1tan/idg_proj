# Benchmark Report

Generated: 2026-04-02T02:51:12.460717+00:00
Source: stored_eval_runs

## Summary

- Scenario instances: 20
- Scenario families: 5
- Hierarchy win rate: 0.650
- Flat win rate: 0.000
- Tie rate: 0.350
- Slot recall mean +/- stddev: baseline 0.660 +/- 0.257, hierarchy 0.803 +/- 0.199
- Keyword recall mean +/- stddev: baseline 0.610 +/- 0.205, hierarchy 0.803 +/- 0.199
- Retrieved tokens mean +/- stddev: baseline 12.9 +/- 2.0, hierarchy 21.1 +/- 8.6
- Average slot recall gain: 0.143
- Average keyword recall gain: 0.193
- Average retrieved token delta: -8.2

## Family Aggregates

| Family | Instances | Hierarchy Win Rate | Flat Win Rate | Slot Recall Gain | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| commitment_revision | 4 | 1.000 | 0.000 | 0.000 | -18.8 |
| delayed_commitment | 4 | 0.250 | 0.000 | 0.050 | -3.0 |
| identity_shift | 4 | 1.000 | 0.000 | 0.417 | -15.5 |
| relationship_context | 4 | 1.000 | 0.000 | 0.250 | -3.5 |
| routine_interruption | 4 | 0.000 | 0.000 | 0.000 | 0.0 |

## Scenario Instances

| Scenario | Seed | Winner | Baseline Slot Recall | Hierarchy Slot Recall | Baseline Tokens | Hierarchy Tokens |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| delayed_commitment__seed_11 | 11 | tie | 0.800 | 0.800 | 15.0 | 15.0 |
| delayed_commitment__seed_23 | 23 | tie | 0.800 | 0.800 | 15.0 | 15.0 |
| delayed_commitment__seed_37 | 37 | tie | 0.800 | 0.800 | 14.0 | 14.0 |
| delayed_commitment__seed_53 | 53 | hierarchy | 0.800 | 1.000 | 15.0 | 27.0 |
| routine_interruption__seed_11 | 11 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| routine_interruption__seed_23 | 23 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| routine_interruption__seed_37 | 37 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| routine_interruption__seed_53 | 53 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| relationship_context__seed_11 | 11 | hierarchy | 0.250 | 0.500 | 13.0 | 17.0 |
| relationship_context__seed_23 | 23 | hierarchy | 0.250 | 0.500 | 13.0 | 16.0 |
| relationship_context__seed_37 | 37 | hierarchy | 0.250 | 0.500 | 13.0 | 16.0 |
| relationship_context__seed_53 | 53 | hierarchy | 0.250 | 0.500 | 13.0 | 17.0 |
| commitment_revision__seed_11 | 11 | hierarchy | 1.000 | 1.000 | 15.0 | 34.0 |
| commitment_revision__seed_23 | 23 | hierarchy | 1.000 | 1.000 | 13.0 | 32.0 |
| commitment_revision__seed_37 | 37 | hierarchy | 1.000 | 1.000 | 12.0 | 30.0 |
| commitment_revision__seed_53 | 53 | hierarchy | 1.000 | 1.000 | 15.0 | 34.0 |
| identity_shift__seed_11 | 11 | hierarchy | 0.667 | 1.000 | 12.0 | 29.0 |
| identity_shift__seed_23 | 23 | hierarchy | 0.667 | 1.000 | 11.0 | 28.0 |
| identity_shift__seed_37 | 37 | hierarchy | 0.333 | 1.000 | 17.0 | 28.0 |
| identity_shift__seed_53 | 53 | hierarchy | 0.667 | 1.000 | 12.0 | 29.0 |

## Notes

- `delayed_commitment__seed_11`: Long-horizon recall after many irrelevant routines.
- `delayed_commitment__seed_23`: Long-horizon recall after many irrelevant routines.
- `delayed_commitment__seed_37`: Long-horizon recall after many irrelevant routines.
- `delayed_commitment__seed_53`: Long-horizon recall after many irrelevant routines.
- `routine_interruption__seed_11`: Rare pivotal event should survive routine repetition.
- `routine_interruption__seed_23`: Rare pivotal event should survive routine repetition.
- `routine_interruption__seed_37`: Rare pivotal event should survive routine repetition.
- `routine_interruption__seed_53`: Rare pivotal event should survive routine repetition.
- `relationship_context__seed_11`: Relationship context should remain recoverable as actionable guidance.
- `relationship_context__seed_23`: Relationship context should remain recoverable as actionable guidance.
- `relationship_context__seed_37`: Relationship context should remain recoverable as actionable guidance.
- `relationship_context__seed_53`: Relationship context should remain recoverable as actionable guidance.
- `commitment_revision__seed_11`: Later corrective evidence should dominate outdated commitments.
- `commitment_revision__seed_23`: Later corrective evidence should dominate outdated commitments.
- `commitment_revision__seed_37`: Later corrective evidence should dominate outdated commitments.
- `commitment_revision__seed_53`: Later corrective evidence should dominate outdated commitments.
- `identity_shift__seed_11`: The system should favor the updated self-model over obsolete self-description.
- `identity_shift__seed_23`: The system should favor the updated self-model over obsolete self-description.
- `identity_shift__seed_37`: The system should favor the updated self-model over obsolete self-description.
- `identity_shift__seed_53`: The system should favor the updated self-model over obsolete self-description.
