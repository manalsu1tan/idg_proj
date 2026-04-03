# Benchmark Report

Generated: 2026-04-01T21:47:03.028252+00:00
Source: stored_eval_runs

## Summary

- Scenario instances: 20
- Scenario families: 5
- Hierarchy win rate: 0.200
- Flat win rate: 0.400
- Tie rate: 0.400
- Slot recall mean +/- stddev: baseline 0.767 +/- 0.311, hierarchy 0.842 +/- 0.212
- Keyword recall mean +/- stddev: baseline 0.717 +/- 0.289, hierarchy 0.792 +/- 0.198
- Retrieved tokens mean +/- stddev: baseline 13.9 +/- 1.6, hierarchy 20.1 +/- 5.8
- Average slot recall gain: 0.075
- Average keyword recall gain: 0.075
- Average retrieved token delta: -6.2

## Family Aggregates

| Family | Instances | Hierarchy Win Rate | Flat Win Rate | Slot Recall Gain | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| commitment_revision | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| delayed_commitment | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| identity_shift | 4 | 0.000 | 1.000 | 0.000 | -9.5 |
| relationship_context | 4 | 1.000 | 0.000 | 0.375 | -15.5 |
| routine_interruption | 4 | 0.000 | 1.000 | 0.000 | -6.0 |

## Scenario Instances

| Scenario | Seed | Winner | Baseline Slot Recall | Hierarchy Slot Recall | Baseline Tokens | Hierarchy Tokens |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| delayed_commitment__seed_11 | 11 | tie | 1.000 | 1.000 | 14.0 | 14.0 |
| delayed_commitment__seed_23 | 23 | tie | 1.000 | 1.000 | 14.0 | 14.0 |
| delayed_commitment__seed_37 | 37 | tie | 1.000 | 1.000 | 13.0 | 13.0 |
| delayed_commitment__seed_53 | 53 | tie | 1.000 | 1.000 | 14.0 | 14.0 |
| routine_interruption__seed_11 | 11 | flat | 1.000 | 1.000 | 16.0 | 22.0 |
| routine_interruption__seed_23 | 23 | flat | 1.000 | 1.000 | 16.0 | 22.0 |
| routine_interruption__seed_37 | 37 | flat | 1.000 | 1.000 | 16.0 | 22.0 |
| routine_interruption__seed_53 | 53 | flat | 1.000 | 1.000 | 16.0 | 22.0 |
| relationship_context__seed_11 | 11 | hierarchy | 0.250 | 0.750 | 13.0 | 28.0 |
| relationship_context__seed_23 | 23 | hierarchy | 0.250 | 0.500 | 13.0 | 29.0 |
| relationship_context__seed_37 | 37 | hierarchy | 0.250 | 0.500 | 13.0 | 29.0 |
| relationship_context__seed_53 | 53 | hierarchy | 0.250 | 0.750 | 13.0 | 28.0 |
| commitment_revision__seed_11 | 11 | tie | 1.000 | 1.000 | 15.0 | 15.0 |
| commitment_revision__seed_23 | 23 | tie | 1.000 | 1.000 | 13.0 | 13.0 |
| commitment_revision__seed_37 | 37 | tie | 1.000 | 1.000 | 12.0 | 12.0 |
| commitment_revision__seed_53 | 53 | tie | 1.000 | 1.000 | 15.0 | 15.0 |
| identity_shift__seed_11 | 11 | flat | 0.667 | 0.667 | 12.0 | 21.0 |
| identity_shift__seed_23 | 23 | flat | 0.667 | 0.667 | 11.0 | 20.0 |
| identity_shift__seed_37 | 37 | flat | 0.333 | 0.333 | 17.0 | 27.0 |
| identity_shift__seed_53 | 53 | flat | 0.667 | 0.667 | 12.0 | 22.0 |

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
