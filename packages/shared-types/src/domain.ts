export interface FighterSummary {
  id: string;
  fighter_id?: string;
  first_name: string;
  last_name: string;
  nickname: string | null;
  stance: string | null;
  height_cm: number | null;
  reach_cm: number | null;
  weight_class: string | null;
  division?: string | null;
  display_name?: string | null;
}

export interface DivisionStandout {
  fighter_id: string;
  display_name: string;
  wins: number;
  losses: number;
  form_score: number;
  last_bout_date: string;
}

export interface DivisionStandoutsResponse {
  as_of_date: string | null;
  window_start: string | null;
  divisions: Array<{
    code: string;
    label: string;
    fighters: DivisionStandout[];
  }>;
}

export interface FighterCareerStats {
  wins: number;
  losses: number;
  draws: number;
  ko_wins: number;
  sub_wins: number;
  dec_wins: number;
  avg_fight_time_mins: number | null;
  sig_strike_landed_per_min: number | null;
  sig_strike_acc: number | null;
  sig_strike_absorbed_per_min: number | null;
  sig_strike_def: number | null;
  td_avg_per_15m: number | null;
  td_acc: number | null;
  td_def: number | null;
  sub_avg_per_15m: number | null;
}

export interface FighterDetail extends FighterSummary {
  stats: FighterCareerStats | null;
  bouts: FightSummary[];
}

export interface FightSummary {
  id: string;
  fight_id?: string;
  fight_date?: string;
  division_code?: string | null;
  scheduled_rounds?: number;
  date: string;
  promotion: string;
  event_name: string;
  fighter_a_id: string;
  fighter_a_name: string;
  fighter_b_id: string;
  fighter_b_name: string;
  winner_id: string | null;
  winner_name?: string | null;
  method: string | null;
  finish_round: number | null;
  finish_time: string | null;
  is_title_fight: boolean;
  weight_class: string | null;
  participants?: Array<{ fighter_id: string; display_name: string }>;
  result?: { winner_fighter_id?: string | null; outcome_type?: string; canonical_method_code?: string | null; source_method_label?: string | null } | null;
}

export interface MethodProbabilities {
  fighter_a_ko: number;
  fighter_a_sub: number;
  fighter_a_dec: number;
  fighter_b_ko: number;
  fighter_b_sub: number;
  fighter_b_dec: number;
}

export interface MatchupPrediction {
  fighter_a_id: string;
  fighter_b_id: string;
  fighter_a_name: string;
  fighter_b_name: string;
  fighter_a_win_prob: number;
  fighter_b_win_prob: number;
  confidence_score: number;
  model_version: string;
  generated_at: string;
  prediction_cutoff: string;
  limitations?: string[];
    method_probabilities?: MethodProbabilities;
    round_probabilities?: Record<string, number>;
    duration_expected_seconds?: number;
}

export interface UpcomingBout {
  id: string;
  bout_order: number;
  weight_class: string | null;
  rounds: number;
  is_title_fight: boolean;
  fighter_a_id: string;
  fighter_a_name: string;
  fighter_b_id: string;
  fighter_b_name: string;
  fighter_a_win_prob: number;
  fighter_b_win_prob: number;
  confidence_score: number;
  model_version: string;
  prediction_cutoff: string;
  fighter_a?: any;
  fighter_b?: any;
  probability_a?: number;
  probability_b?: number;
  is_title_bout?: boolean;
  card_placement?: string;
}

export interface EventDetail {
  event_id: string;
  event_name: string;
  event_date: string;
  location: string;
  venue?: string;
  card_type?: string;
  status?: string;
  source_audit_state?: string;
  bout_count?: number;
  bouts: UpcomingBout[];
}

export interface CounterfactualAdjustments {
  reach_cm?: number;
  height_cm?: number;
  striking_defense?: number;
  takedown_defense?: number;
  striking_volume?: number;
}

export interface SimulationRequest {
  fighter_a_id: string;
  fighter_b_id: string;
  rounds?: number;
  iterations?: number;
  counterfactual_adjustments?: {
    fighter_a?: CounterfactualAdjustments;
    fighter_b?: CounterfactualAdjustments;
  };
}

export interface SimulationResult {
  simulation_id: string;
  fighter_a_win_prob: number;
  fighter_b_win_prob: number;
  base_probabilities: {
    fighter_a_win_prob: number;
    fighter_b_win_prob: number;
  };
  delta_probabilities: {
    fighter_a_win_prob_delta: number;
    fighter_b_win_prob_delta: number;
  };
  round_distribution: Record<string, number>;
  method_distribution: Record<string, number>;
  iterations_run: number;
  plausibility_score: number;
  synthetic_factors_applied: string[];
}

export interface SimilarMatchup {
  bout_id: string;
  fighter_a_name: string;
  fighter_b_name: string;
  date: string;
  event_name: string;
  similarity_score: number;
  winner_name: string | null;
  method: string | null;
  round: number | null;
}

export interface AttributionFactor {
  feature_name: string;
  feature_group: string;
  value_a: number | null;
  value_b: number | null;
  raw_impact: number;
  normalized_importance: number;
  direction_fighter: string;
}

export interface FreshnessStatus {
  source_id: string;
  stable_key: string;
  display_name: string;
  source_type: string;
  audit_state: string;
  dataset_license: string | null;
  last_observation_timestamp: string | null;
  last_retrieval_timestamp: string | null;
  last_published_timestamp: string | null;
  published_records_count: number;
  quarantined_records_count: number;
  open_quality_issues_count: number;
  status: string;
}

export interface DataFreshnessResponse {
  sources: FreshnessStatus[];
  accepted_dataset_generation_id: string;
  prediction_cutoff_date: string;
  summary_timestamp: string;
  limitations: string[];
}

export interface ModelCard {
  model_id: string;
  architecture: string;
  version: string;
  training_cutoff: string;
  test_brier_score: number;
  test_log_loss: number;
  test_roc_auc: number;
  calibration_error: number;
  calibrated_bins: Array<{
    bin_min: number;
    bin_max: number;
    mean_predicted: number;
    empirical_frequency: number;
    sample_count: number;
  }>;
}

export interface PublicModelCard {
  model_id: string;
  family: string;
  promotion_status: string;
  feature_count: number;
  feature_schema_version: string;
  training_cutoff_date: string;
  bundle_hash: string;
  limitations: string[];
}

export interface ModelEvaluation {
  model_id: string;
  bundle_hash: string;
  metrics: {
    roc_auc: number;
    brier_score: number;
    log_loss: number;
    evaluated_row_count: number;
  };
  calibration_bins: Array<{
    lower_inclusive: number;
    upper_exclusive: number | null;
    count: number;
    mean_predicted_probability: number | null;
    observed_positive_rate: number | null;
  }>;
  limitations: string[];
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface CounterfactualResult {
  fighter_a_id: string;
  fighter_b_id: string;
  base_probability_a: number;
  base_probability_b: number;
  counterfactual_probability_a: number;
  counterfactual_probability_b: number;
  probability_delta_a: number;
  adjustments_applied: Record<string, number>;
  plausibility_warnings: string[];
  synthetic_label: string;
}

export interface MonteCarloResult {
  fighter_a_id: string;
  fighter_b_id: string;
  iterations: number;
  win_probability_a: number;
  win_probability_b: number;
  method_probabilities: { decision: number; ko_tko: number; submission: number };
  round_distribution: {
    round_1: number;
    round_2: number;
    round_3: number;
    round_4?: number | null;
    round_5?: number | null;
  };
  median_duration_seconds: number;
  mean_duration_seconds: number;
  seed: number;
}

export interface ExplanationFactor {
  factor_name: string;
  category: string;
  impact_score: number;
  direction: string;
  description: string;
}

export interface ExplanationResult {
  fighter_a_id: string;
  fighter_b_id: string;
  model_version: string;
  top_factors: ExplanationFactor[];
  model_factors?: Array<{
    factor_name: string;
    impact_probability_points: number;
    direction: string;
    description: string;
  }>;
  model_baseline_probability_a?: number;
  missing_data_caveats: string[];
  disclaimer: string;
  algorithm?: string;
  baseline_cohort?: string;
  stylistic_summary?: string;
}
