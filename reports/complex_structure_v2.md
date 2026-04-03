# Benchmark Report

Generated: 2026-04-02T05:50:43.458844+00:00
Source: stored_eval_runs

## Summary

- Scenario instances: 48
- Scenario families: 12
- Hierarchy win rate: 0.271
- Flat win rate: 0.062
- Tie rate: 0.667
- Slot recall mean +/- stddev: baseline 0.706 +/- 0.256, hierarchy 0.789 +/- 0.194
- Keyword recall mean +/- stddev: baseline 0.693 +/- 0.226, hierarchy 0.775 +/- 0.188
- Retrieved tokens mean +/- stddev: baseline 11.2 +/- 2.3, hierarchy 13.4 +/- 6.1
- Average slot recall gain: 0.083
- Average keyword recall gain: 0.082
- Average retrieved token delta: -2.3

## Family Aggregates

| Family | Instances | Hierarchy Win Rate | Flat Win Rate | Slot Recall Gain | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| commitment_revision | 4 | 0.250 | 0.750 | 0.000 | -8.8 |
| contradictory_near_duplicates | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| cross_event_composition | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| delayed_commitment | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| identity_shift | 4 | 1.000 | 0.000 | 0.417 | -15.5 |
| multi_person_interference | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| negation_traps | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| pronoun_alias_ambiguity | 4 | 1.000 | 0.000 | 0.333 | 0.5 |
| relationship_context | 4 | 1.000 | 0.000 | 0.250 | -3.5 |
| routine_interruption | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| temporal_override_chain | 4 | 0.000 | 0.000 | 0.000 | 0.0 |
| time_window_pressure | 4 | 0.000 | 0.000 | 0.000 | 0.0 |

## Scenario Instances

| Scenario | Seed | Winner | Baseline Slot Recall | Hierarchy Slot Recall | Baseline Tokens | Hierarchy Tokens |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| delayed_commitment__seed_11 | 11 | tie | 0.800 | 0.800 | 15.0 | 15.0 |
| delayed_commitment__seed_23 | 23 | tie | 0.800 | 0.800 | 15.0 | 15.0 |
| delayed_commitment__seed_37 | 37 | tie | 0.800 | 0.800 | 14.0 | 14.0 |
| delayed_commitment__seed_53 | 53 | tie | 0.800 | 0.800 | 15.0 | 15.0 |
| routine_interruption__seed_11 | 11 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| routine_interruption__seed_23 | 23 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| routine_interruption__seed_37 | 37 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| routine_interruption__seed_53 | 53 | tie | 0.667 | 0.667 | 10.0 | 10.0 |
| relationship_context__seed_11 | 11 | hierarchy | 0.250 | 0.500 | 13.0 | 17.0 |
| relationship_context__seed_23 | 23 | hierarchy | 0.250 | 0.500 | 13.0 | 16.0 |
| relationship_context__seed_37 | 37 | hierarchy | 0.250 | 0.500 | 13.0 | 16.0 |
| relationship_context__seed_53 | 53 | hierarchy | 0.250 | 0.500 | 13.0 | 17.0 |
| commitment_revision__seed_11 | 11 | flat | 1.000 | 1.000 | 15.0 | 23.0 |
| commitment_revision__seed_23 | 23 | flat | 1.000 | 1.000 | 13.0 | 21.0 |
| commitment_revision__seed_37 | 37 | hierarchy | 1.000 | 1.000 | 12.0 | 23.0 |
| commitment_revision__seed_53 | 53 | flat | 1.000 | 1.000 | 15.0 | 23.0 |
| identity_shift__seed_11 | 11 | hierarchy | 0.667 | 1.000 | 12.0 | 29.0 |
| identity_shift__seed_23 | 23 | hierarchy | 0.667 | 1.000 | 11.0 | 28.0 |
| identity_shift__seed_37 | 37 | hierarchy | 0.333 | 1.000 | 17.0 | 28.0 |
| identity_shift__seed_53 | 53 | hierarchy | 0.667 | 1.000 | 12.0 | 29.0 |
| temporal_override_chain__seed_11 | 11 | tie | 1.000 | 1.000 | 11.0 | 11.0 |
| temporal_override_chain__seed_23 | 23 | tie | 1.000 | 1.000 | 11.0 | 11.0 |
| temporal_override_chain__seed_37 | 37 | tie | 1.000 | 1.000 | 10.0 | 10.0 |
| temporal_override_chain__seed_53 | 53 | tie | 1.000 | 1.000 | 11.0 | 11.0 |
| cross_event_composition__seed_11 | 11 | tie | 0.500 | 0.500 | 8.0 | 8.0 |
| cross_event_composition__seed_23 | 23 | tie | 0.500 | 0.500 | 8.0 | 8.0 |
| cross_event_composition__seed_37 | 37 | tie | 0.500 | 0.500 | 9.0 | 9.0 |
| cross_event_composition__seed_53 | 53 | tie | 0.500 | 0.500 | 8.0 | 8.0 |
| contradictory_near_duplicates__seed_11 | 11 | tie | 1.000 | 1.000 | 12.0 | 12.0 |
| contradictory_near_duplicates__seed_23 | 23 | tie | 1.000 | 1.000 | 13.0 | 13.0 |
| contradictory_near_duplicates__seed_37 | 37 | tie | 1.000 | 1.000 | 13.0 | 13.0 |
| contradictory_near_duplicates__seed_53 | 53 | tie | 1.000 | 1.000 | 12.0 | 12.0 |
| pronoun_alias_ambiguity__seed_11 | 11 | hierarchy | 0.333 | 0.667 | 9.0 | 9.0 |
| pronoun_alias_ambiguity__seed_23 | 23 | hierarchy | 0.333 | 0.667 | 9.0 | 8.0 |
| pronoun_alias_ambiguity__seed_37 | 37 | hierarchy | 0.333 | 0.667 | 9.0 | 8.0 |
| pronoun_alias_ambiguity__seed_53 | 53 | hierarchy | 0.333 | 0.667 | 9.0 | 9.0 |
| multi_person_interference__seed_11 | 11 | tie | 0.667 | 0.667 | 8.0 | 8.0 |
| multi_person_interference__seed_23 | 23 | tie | 0.667 | 0.667 | 8.0 | 8.0 |
| multi_person_interference__seed_37 | 37 | tie | 0.667 | 0.667 | 8.0 | 8.0 |
| multi_person_interference__seed_53 | 53 | tie | 0.667 | 0.667 | 8.0 | 8.0 |
| negation_traps__seed_11 | 11 | tie | 0.667 | 0.667 | 11.0 | 11.0 |
| negation_traps__seed_23 | 23 | tie | 0.667 | 0.667 | 11.0 | 11.0 |
| negation_traps__seed_37 | 37 | tie | 0.667 | 0.667 | 11.0 | 11.0 |
| negation_traps__seed_53 | 53 | tie | 0.667 | 0.667 | 11.0 | 11.0 |
| time_window_pressure__seed_11 | 11 | tie | 1.000 | 1.000 | 10.0 | 10.0 |
| time_window_pressure__seed_23 | 23 | tie | 1.000 | 1.000 | 10.0 | 10.0 |
| time_window_pressure__seed_37 | 37 | tie | 1.000 | 1.000 | 10.0 | 10.0 |
| time_window_pressure__seed_53 | 53 | tie | 1.000 | 1.000 | 10.0 | 10.0 |

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
- `temporal_override_chain__seed_11`: Multiple revisions require selecting the final override over earlier plans.
- `temporal_override_chain__seed_23`: Multiple revisions require selecting the final override over earlier plans.
- `temporal_override_chain__seed_37`: Multiple revisions require selecting the final override over earlier plans.
- `temporal_override_chain__seed_53`: Multiple revisions require selecting the final override over earlier plans.
- `cross_event_composition__seed_11`: Answer requires composing guidance spread across multiple events.
- `cross_event_composition__seed_23`: Answer requires composing guidance spread across multiple events.
- `cross_event_composition__seed_37`: Answer requires composing guidance spread across multiple events.
- `cross_event_composition__seed_53`: Answer requires composing guidance spread across multiple events.
- `contradictory_near_duplicates__seed_11`: Near-duplicate facts conflict; retriever should prefer corrected evidence.
- `contradictory_near_duplicates__seed_23`: Near-duplicate facts conflict; retriever should prefer corrected evidence.
- `contradictory_near_duplicates__seed_37`: Near-duplicate facts conflict; retriever should prefer corrected evidence.
- `contradictory_near_duplicates__seed_53`: Near-duplicate facts conflict; retriever should prefer corrected evidence.
- `pronoun_alias_ambiguity__seed_11`: Pronouns and aliases require entity resolution across events.
- `pronoun_alias_ambiguity__seed_23`: Pronouns and aliases require entity resolution across events.
- `pronoun_alias_ambiguity__seed_37`: Pronouns and aliases require entity resolution across events.
- `pronoun_alias_ambiguity__seed_53`: Pronouns and aliases require entity resolution across events.
- `multi_person_interference__seed_11`: Two similar relationship threads compete; retrieval must isolate the target person.
- `multi_person_interference__seed_23`: Two similar relationship threads compete; retrieval must isolate the target person.
- `multi_person_interference__seed_37`: Two similar relationship threads compete; retrieval must isolate the target person.
- `multi_person_interference__seed_53`: Two similar relationship threads compete; retrieval must isolate the target person.
- `negation_traps__seed_11`: Negation and corrections test resistance to lexical traps.
- `negation_traps__seed_23`: Negation and corrections test resistance to lexical traps.
- `negation_traps__seed_37`: Negation and corrections test resistance to lexical traps.
- `negation_traps__seed_53`: Negation and corrections test resistance to lexical traps.
- `time_window_pressure__seed_11`: Older but durable facts should beat newer irrelevant updates.
- `time_window_pressure__seed_23`: Older but durable facts should beat newer irrelevant updates.
- `time_window_pressure__seed_37`: Older but durable facts should beat newer irrelevant updates.
- `time_window_pressure__seed_53`: Older but durable facts should beat newer irrelevant updates.
