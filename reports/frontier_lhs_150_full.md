# Frontier Sweep Report

Generated: 2026-04-03T05:30:37.652265+00:00
Sampling method: lhs
Candidates evaluated: 151
Frontier size: 6

## Objective Slices

| Slice | Weight | Seeds | Perturbations |
| --- | ---: | --- | --- |
| canonical | 0.500 | 11,23,37,53 | - |
| unseen_seeds | 0.250 | 111,123,137,153 | - |
| hard_perturbations | 0.250 | 11,23,37,53 | concise,indirect,colloquial,typo_noise,word_order,entity_swap_distractor |

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
| candidate_0085 | 0.981 | 0.291 | 0.300 | 0.669 | -7.479 |
| candidate_0076 | 0.975 | 0.291 | 0.299 | 0.668 | -7.321 |
| candidate_0124 | 0.968 | 0.291 | 0.300 | 0.670 | -8.524 |
| candidate_0031 | 0.476 | 0.267 | 0.275 | 0.600 | -7.191 |
| candidate_0125 | 0.449 | 0.265 | 0.273 | 0.595 | -7.099 |
| candidate_0112 | 0.383 | 0.263 | 0.272 | 0.589 | -7.906 |

## Top Candidates

| Candidate | Frontier | Utility | Worst Slot Gain | Worst Keyword Gain | Flat Win Penalty |
| --- | --- | ---: | ---: | ---: | ---: |
| candidate_0085 | yes | 0.981 | 0.287 | 0.291 | -0.003 |
| candidate_0017 | no | 0.977 | 0.287 | 0.291 | -0.003 |
| candidate_0076 | yes | 0.975 | 0.285 | 0.290 | -0.004 |
| candidate_0049 | no | 0.974 | 0.287 | 0.291 | -0.008 |
| candidate_0149 | no | 0.974 | 0.287 | 0.291 | -0.008 |
| candidate_0093 | no | 0.973 | 0.287 | 0.291 | -0.010 |
| candidate_0124 | yes | 0.968 | 0.288 | 0.293 | -0.005 |
| candidate_0063 | no | 0.968 | 0.285 | 0.290 | -0.004 |
| candidate_0142 | no | 0.968 | 0.285 | 0.290 | -0.004 |
| candidate_0122 | no | 0.965 | 0.288 | 0.293 | -0.009 |
| baseline | no | 0.963 | 0.284 | 0.289 | -0.004 |
| candidate_0132 | no | 0.962 | 0.287 | 0.291 | -0.013 |
| candidate_0136 | no | 0.962 | 0.287 | 0.291 | -0.010 |
| candidate_0087 | no | 0.956 | 0.286 | 0.291 | -0.016 |
| candidate_0113 | no | 0.954 | 0.284 | 0.289 | -0.011 |
| candidate_0020 | no | 0.953 | 0.288 | 0.293 | -0.009 |
| candidate_0013 | no | 0.953 | 0.285 | 0.290 | -0.003 |
| candidate_0127 | no | 0.951 | 0.284 | 0.289 | -0.003 |
| candidate_0055 | no | 0.950 | 0.282 | 0.287 | -0.004 |
| candidate_0048 | no | 0.948 | 0.287 | 0.291 | -0.010 |
| candidate_0121 | no | 0.947 | 0.285 | 0.290 | -0.003 |
| candidate_0002 | no | 0.944 | 0.288 | 0.293 | -0.009 |
| candidate_0126 | no | 0.944 | 0.288 | 0.293 | -0.009 |
| candidate_0139 | no | 0.944 | 0.288 | 0.293 | -0.009 |
| candidate_0140 | no | 0.943 | 0.288 | 0.293 | -0.009 |
