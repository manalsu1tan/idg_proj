# Frontier Sweep Report

Generated: 2026-04-09T14:33:14.275818+00:00
Sampling method: lhs
Optimization random seeds: 7
Candidates evaluated: 3
Frontier size: 3

## Objective Slices

| Slice | Weight | Seeds | Perturbations |
| --- | ---: | --- | --- |
| canonical | 0.500 | 11 | - |
| unseen_seeds | 0.250 | 111 | - |
| hard_perturbations | 0.250 | 11 | concise,indirect,typo_noise |

## Sweep Dimensions

- `resolver_thresholds.competing_person_score_gap`: [0.1, 0.4] (float)
- `resolver_thresholds.competing_person_score_ratio`: [0.45, 0.75] (float)
- `resolver_thresholds.competing_person_window`: [4, 12] (int)
- `resolver_thresholds.disambiguation_close_margin`: [0.04, 0.16] (float)
- `resolver_thresholds.expansion_branch_target`: [2, 4] (int)
- `resolver_thresholds.low_confidence_margin`: [0.04, 0.16] (float)
- `strategy_thresholds.coverage_min`: [0.34, 0.58] (float)
- `strategy_thresholds.feature_active_min`: [0.24, 0.44] (float)
- `strategy_thresholds.hierarchy_expand_min`: [0.38, 0.62] (float)
- `strategy_thresholds.multi_branch_min`: [0.52, 0.78] (float)
- `strategy_thresholds.revision_leaf_min`: [0.34, 0.58] (float)
- `supplemental_thresholds.base_utility_threshold`: [0.03, 0.14] (float)
- `supplemental_thresholds.communication_gap_relax`: [0, 0.05] (float)
- `supplemental_thresholds.disambiguation_relax`: [0, 0.07] (float)
- `supplemental_thresholds.low_confidence_relax`: [0, 0.03] (float)
- `supplemental_thresholds.max_utility_threshold`: [0.1, 0.24] (float)
- `supplemental_thresholds.min_utility_threshold`: [0.01, 0.08] (float)
- `supplemental_thresholds.missing_required_relax`: [0, 0.05] (float)
- `supplemental_thresholds.polarity_relax`: [0, 0.05] (float)
- `supplemental_thresholds.temporal_only_penalty`: [0, 0.08] (float)
- `supplemental_weights.communication_bonus`: [0.04, 0.18] (float)
- `supplemental_weights.coverage_bonus_per_key`: [0.02, 0.12] (float)
- `supplemental_weights.disambiguation_bonus`: [0.04, 0.18] (float)
- `supplemental_weights.entity_aligned_bonus`: [0, 0.08] (float)
- `supplemental_weights.polarity_bonus`: [0.04, 0.18] (float)
- `supplemental_weights.required_bonus_per_key`: [0.06, 0.22] (float)

## Family Objectives

- `multi_person_interference:slot_gain:max`
- `time_window_pressure:token_delta:max`

## Pareto Frontier

| Candidate | Utility | Slot Gain | Keyword Gain | Win Rate | Token Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.500 | 0.156 [0.156, 0.156] | 0.125 | 0.625 | -3.750 [-3.750, -3.750] |
| candidate_0001 | 0.500 | 0.156 [0.156, 0.156] | 0.125 | 0.625 | -3.750 [-3.750, -3.750] |
| candidate_0002 | 0.500 | 0.156 [0.156, 0.156] | 0.125 | 0.625 | -3.750 [-3.750, -3.750] |

## Top Candidates

| Candidate | Frontier | Utility | Worst Slot Gain | Worst Keyword Gain | Flat Win Penalty |
| --- | --- | ---: | ---: | ---: | ---: |
| baseline | yes | 0.500 | 0.125 | 0.100 | -0.000 |
| candidate_0001 | yes | 0.500 | 0.125 | 0.100 | -0.000 |
| candidate_0002 | yes | 0.500 | 0.125 | 0.100 | -0.000 |
