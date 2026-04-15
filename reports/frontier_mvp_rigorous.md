# Frontier Sweep Report

Generated: 2026-04-15T12:30:00.178230+00:00
Sampling method: lhs
Optimization random seeds: 7,8,9
Candidates evaluated: 49
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
| candidate_0028 | 0.965 | 0.295 [0.273, 0.311] | 0.302 | 0.662 | -7.467 [-7.927, -6.823] |
| candidate_0027 | 0.964 | 0.296 [0.273, 0.313] | 0.304 | 0.667 | -8.808 [-9.699, -7.613] |
| candidate_0040 | 0.954 | 0.295 [0.273, 0.311] | 0.302 | 0.662 | -8.118 [-8.720, -7.290] |
| candidate_0017 | 0.950 | 0.293 [0.270, 0.310] | 0.301 | 0.662 | -7.446 [-7.901, -6.807] |
| candidate_0035 | 0.415 | 0.274 [0.252, 0.290] | 0.281 | 0.600 | -7.040 [-7.498, -6.398] |
| candidate_0018 | 0.412 | 0.275 [0.252, 0.292] | 0.283 | 0.604 | -8.511 [-9.355, -7.374] |

## Top Candidates

| Candidate | Frontier | Utility | Worst Slot Gain | Worst Keyword Gain | Flat Win Penalty |
| --- | --- | ---: | ---: | ---: | ---: |
| candidate_0028 | yes | 0.965 | 0.290 | 0.300 | -0.004 |
| candidate_0027 | yes | 0.964 | 0.290 | 0.300 | -0.000 |
| candidate_0039 | no | 0.960 | 0.290 | 0.300 | -0.004 |
| candidate_0040 | yes | 0.954 | 0.290 | 0.300 | -0.000 |
| candidate_0011 | no | 0.952 | 0.290 | 0.300 | -0.000 |
| candidate_0017 | yes | 0.950 | 0.290 | 0.300 | -0.004 |
| candidate_0002 | no | 0.946 | 0.290 | 0.297 | -0.004 |
| candidate_0009 | no | 0.939 | 0.290 | 0.300 | -0.000 |
| candidate_0015 | no | 0.922 | 0.290 | 0.294 | -0.000 |
| baseline | no | 0.913 | 0.290 | 0.291 | -0.004 |
| candidate_0034 | no | 0.910 | 0.290 | 0.294 | -0.000 |
| candidate_0032 | no | 0.891 | 0.287 | 0.287 | -0.004 |
| candidate_0003 | no | 0.835 | 0.290 | 0.300 | -0.062 |
| candidate_0004 | no | 0.827 | 0.290 | 0.300 | -0.062 |
| candidate_0041 | no | 0.827 | 0.290 | 0.300 | -0.062 |
| candidate_0016 | no | 0.809 | 0.278 | 0.278 | -0.004 |
| candidate_0033 | no | 0.808 | 0.290 | 0.300 | -0.062 |
| candidate_0024 | no | 0.806 | 0.277 | 0.277 | -0.004 |
| candidate_0013 | no | 0.804 | 0.277 | 0.277 | -0.004 |
| candidate_0038 | no | 0.797 | 0.290 | 0.294 | -0.067 |
| candidate_0047 | no | 0.796 | 0.290 | 0.298 | -0.062 |
| candidate_0029 | no | 0.786 | 0.274 | 0.274 | -0.004 |
| candidate_0045 | no | 0.783 | 0.274 | 0.274 | -0.004 |
| candidate_0030 | no | 0.781 | 0.274 | 0.274 | -0.004 |
| candidate_0046 | no | 0.755 | 0.287 | 0.287 | -0.067 |

## Stability Report

- Mode count across runs: 4
- Average pairwise mode Jaccard: 0.639

| Mode | Appearance Rate | Run Count | Candidate Occurrences | Slot Gain Range | Token Delta Range |
| --- | ---: | ---: | ---: | ---: | ---: |
| mode_01 | 1.000 | 3 | 10 | 0.0028 | 0.9042 |
| mode_02 | 1.000 | 3 | 4 | 0.0008 | 1.0146 |
| mode_03 | 0.667 | 2 | 3 | 0.0050 | 0.4417 |
| mode_04 | 0.333 | 1 | 1 | 0.0000 | 0.0000 |
