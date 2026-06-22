/** OrbitPulse API type definitions — mirrors backend Pydantic schemas. */

export interface HealthStatus {
  status: string;
  ready: boolean;
  objects_loaded: number;
  conjunctions_found: number;
  stage: string | null;
  progress_pct: number | null;
}

export interface CatalogObject {
  norad_id: number;
  name: string;
  object_type: string;
  rcs_size: string | null;
  country_code: string | null;
}

export interface ISSPosition {
  lat: number;
  lon: number;
  alt_km: number;
  validated: boolean;
  tle_epoch: string;
  timestamp: string;
}

export interface Conjunction {
  id: number;
  obj_a_id: number;
  obj_b_id: number;
  obj_a_name: string | null;
  obj_b_name: string | null;
  tca_time: string;
  miss_distance_km: number;
  prev_miss_distance_km: number | null;
  relative_velocity_kms: number;
  risk_score: number;
  tier: 'ACTION' | 'WATCHLIST' | 'DISMISSED';
  dismiss_reason: string | null;
  both_maneuverable: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConjunctionDetail extends Conjunction {
  obj_a_type: string | null;
  obj_b_type: string | null;
  obj_a_rcs: string | null;
  obj_b_rcs: string | null;
}

export interface FunnelStats {
  total_screened: number;
  watchlist: number;
  action_required: number;
  last_updated: string | null;
}

export interface TimelineEvent {
  tca_time: string;
  risk_score: number;
  tier: 'ACTION' | 'WATCHLIST' | 'DISMISSED';
  obj_b_name: string;
  miss_distance_km: number;
  relative_velocity_kms: number;
}

export interface ManeuverCandidate {
  id: number;
  direction: string;
  delta_v_ms: number;
  burn_time: string;
  new_miss_distance_km: number;
  fuel_cost_kg: number;
  mission_life_impact: {
    days: number;
    pct_of_remaining: number;
  };
  secondary_conjunctions: number;
  status: string;
  rejection_reason: string | null;
}

export interface TradeOffMatrix {
  conjunction: Record<string, unknown>;
  candidates: ManeuverCandidate[];
  recommendation: {
    chosen_id: number | null;
    reasoning: string;
    source: string;
  };
}

export interface NegotiationRound {
  round: number;
  proposer: string;
  proposal: string;
  response: string;
  reasoning: string;
}

export interface NegotiationContract {
  conjunction_id: number;
  rounds: NegotiationRound[];
  outcome: {
    maneuvering_satellite: number;
    burn: Record<string, unknown>;
    contract_hash: string;
    fallback_used: boolean;
    summary: string;
  };
}

export interface SOCRATESMatch {
  our_prediction: Record<string, unknown>;
  socrates_prediction: Record<string, unknown>;
  delta_km: number;
  norad_ids: number[];
}

export interface SOCRATESValidation {
  matches: SOCRATESMatch[];
  last_fetched: string | null;
}

export interface FragmentationResponse {
  fragments_generated: number;
  synthetic_ids: number[];
  parent_norad_id: number;
}

/** WebSocket message types */
export interface WSPositionMessage {
  type: 'positions';
  data: number[][];
  timestamp: string;
  count: number;
}

export interface WSPipelineMessage {
  type: 'pipeline_status';
  data: { stage: string; progress_pct: number };
}

export interface WSAlertMessage {
  type: 'conjunction_alert';
  data: Conjunction;
  timestamp: string;
}

export type WSMessage = WSPositionMessage | WSPipelineMessage | WSAlertMessage | { type: 'ping' };
