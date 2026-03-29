# Benchmark Report

Generated: 2026-03-28T05:02:07.281623+00:00
Source: stored_eval_runs

## Summary

- Scenario instances: 25
- Scenario families: 5
- Hierarchy win rate: 0.640
- Flat win rate: 0.160
- Tie rate: 0.200
- Slot recall mean +/- stddev: baseline 0.613 +/- 0.414, hierarchy 0.707 +/- 0.398
- Keyword recall mean +/- stddev: baseline 0.720 +/- 0.269, hierarchy 0.890 +/- 0.201
- Retrieved tokens mean +/- stddev: baseline 13.8 +/- 1.7, hierarchy 23.4 +/- 8.4
- Average slot recall gain: 0.093
- Average keyword recall gain: 0.170
- Average retrieved token delta: -9.6

## Family Aggregates

| Family | Instances | Hierarchy Win Rate | Flat Win Rate | Slot Recall Gain | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| commitment_revision | 5 | 1.000 | 0.000 | 0.000 | -18.6 |
| delayed_commitment | 5 | 0.400 | 0.600 | -0.067 | -10.6 |
| identity_shift | 5 | 1.000 | 0.000 | 0.333 | -15.2 |
| relationship_context | 5 | 0.800 | 0.200 | 0.200 | -3.4 |
| routine_interruption | 5 | 0.000 | 0.000 | 0.000 | 0.0 |

## Scenario Instances

| Scenario | Seed | Winner | Baseline Slot Recall | Hierarchy Slot Recall | Baseline Tokens | Hierarchy Tokens |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| delayed_commitment | None | hierarchy | 0.000 | 0.000 | 15.0 | 10.0 |
| routine_interruption | None | tie | 0.000 | 0.000 | 16.0 | 16.0 |
| relationship_context | None | flat | 0.000 | 0.000 | 13.0 | 16.0 |
| commitment_revision | None | hierarchy | 0.000 | 0.000 | 12.0 | 30.0 |
| identity_shift | None | hierarchy | 0.000 | 0.000 | 11.0 | 25.0 |
| delayed_commitment__seed_11 | 11 | hierarchy | 1.000 | 1.000 | 14.0 | 13.0 |
| delayed_commitment__seed_23 | 23 | flat | 1.000 | 0.667 | 14.0 | 34.0 |
| delayed_commitment__seed_37 | 37 | flat | 1.000 | 1.000 | 13.0 | 24.0 |
| delayed_commitment__seed_53 | 53 | flat | 1.000 | 1.000 | 14.0 | 42.0 |
| routine_interruption__seed_11 | 11 | tie | 1.000 | 1.000 | 16.0 | 16.0 |
| routine_interruption__seed_23 | 23 | tie | 1.000 | 1.000 | 16.0 | 16.0 |
| routine_interruption__seed_37 | 37 | tie | 1.000 | 1.000 | 16.0 | 16.0 |
| routine_interruption__seed_53 | 53 | tie | 1.000 | 1.000 | 16.0 | 16.0 |
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

- `delayed_commitment`: Long-horizon recall after many irrelevant routines.
- `routine_interruption`: Rare pivotal event should survive routine repetition.
- `relationship_context`: Relationship context should remain recoverable as actionable guidance.
- `commitment_revision`: Later corrective evidence should dominate outdated commitments.
- `identity_shift`: The system should favor the updated self-model over obsolete self-description.
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
