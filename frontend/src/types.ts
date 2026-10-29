// Mirrors the backend's public schemas (src/flipvalue/schemas.py). The website never computes prices.

export type Region = "IN" | "US";
export type Currency = "INR" | "USD";
export type Grade = "excellent" | "good" | "fair" | "poor" | "faulty";
export type EvidenceStatus = "evidence_backed" | "limited" | "estimated" | "mock_only" | "insufficient";
export type RepairType =
  | "battery_replacement"
  | "charging_port_replacement"
  | "screen_replacement"
  | "camera_module_replacement"
  | "audio_component_replacement"
  | "liquid_damage_service"
  | "software_reset";

export interface SourceSummary {
  id: string;
  name: string;
  source_type: string;
  collection_method: string;
  markets: string;
  verified: boolean;
  is_mock: boolean;
  observation_count: number;
  newest_observation: string | null;
}

export interface Meta {
  environment: string;
  method_version: string;
  regions: Record<Region, Currency>;
  data_status: "real" | "estimated" | "mock_only" | "none";
  real_observations: number;
  estimated_observations?: number;
  mock_observations: number;
  mock_data_in_use: boolean;
  newest_real_observation: string | null;
  freshness_days: number;
  sources: SourceSummary[];
}

export interface CatalogueModel {
  id: string;
  manufacturer: string;
  name: string;
  release_date: string | null;
  storage_gb: number[];
  oem_codes: string[];
  evidence: Record<Region, EvidenceStatus>;
}

type Check = "working" | "issue" | "not_tested";

export interface Assessment {
  powers_on: "yes" | "no";
  usable_normally: "yes" | "no" | "unsure";
  screen: "perfect" | "light_scratches" | "heavy_scratches" | "cracked" | "display_fault";
  screen_touch_works?: "yes" | "no";
  body: "like_new" | "light_wear" | "visible_wear" | "heavy_wear" | "cracked_back";
  battery: "normal" | "drains_fast" | "swollen" | "unknown";
  charging: "normal" | "unreliable" | "not_charging";
  cameras: Check;
  audio: Check;
  buttons: Check;
  connectivity: Check;
  liquid_damage: "no" | "yes" | "unsure";
  previous_repairs: string[];
}

export interface ValuationRequest {
  device: { model_id: string; storage_gb?: number };
  region: Region;
  currency: Currency;
  assessment: Assessment;
  repair_type?: RepairType;
}

export interface SourceRef {
  id: string;
  name: string;
  source_type: string;
  verified: boolean;
  is_mock: boolean;
}

export interface Estimate {
  value: number;
  low: number;
  high: number;
  range_method: "p10_p90" | "min_max";
  basis: string;
  basis_label: string;
  quality: "evidence_backed" | "limited" | "modelled";
  observation_count: number;
  oldest_observation: string;
  newest_observation: string;
  sources: SourceRef[];
}

export interface Valuation {
  valuation_id: string;
  method_version: string;
  mock: boolean;
  generated_at: string;
  region: Region;
  currency: Currency;
  status: "ok" | "partial" | "unavailable";
  device: { model_id: string; manufacturer: string; name: string; storage_gb: number; storage_inferred: boolean };
  condition: {
    grade: Grade;
    faults: string[];
    reasons: string[];
    uncertainties: string[];
    not_used: string[];
    safety: string[];
    customer_reported: boolean;
  };
  as_is: Estimate | null;
  as_is_unavailable_reason: string | null;
  repair_type: RepairType | null;
  assumed_grade_after_repair: Grade | null;
  after_repair: Estimate | null;
  after_repair_unavailable_reason: string | null;
  trade_in: Estimate | null;
  explanation: string[];
  warnings: string[];
  value_types?: ValueTypes | null;
}

export interface SavedValuation {
  id: string;
  created_at: string;
  result: Valuation;
}

export interface SaveResponse {
  id: string;
  delete_token: string;
  result: Valuation;
}

export interface DecisionInput {
  currency: Currency;
  as_is_value?: number;
  after_repair_value?: number;
  repair_cost?: number;
  repair_cost_basis: "user_supplied" | "estimated" | "verified_quote";
  selling_fee_pct: number;
  selling_fixed_cost: number;
  replacement_price?: number;
}

export interface Scenario {
  key: string;
  title: string;
  available: boolean;
  missing: string[];
  gross: number | null;
  selling_fees: number | null;
  other_costs: number | null;
  net: number | null;
  explanation: string;
}

export interface DecisionResult {
  currency: Currency;
  scenarios: Scenario[];
  repair_first_advantage: number | null;
  assumptions: string[];
}

export interface TrendPoint {
  month: string;
  median: number;
  count: number;
}

export interface Trend {
  model_id: string;
  storage_gb: number;
  region: Region;
  currency: Currency;
  grade: Grade;
  available: boolean;
  reason: string | null;
  series: Record<string, TrendPoint[]>;
  min_observations_per_month: number;
  mock_data_excluded: boolean;
}

// --- value types, marketplace, accounts and keys (backend: schemas.py, marketplace/service.py, routes/account.py)

export type Confidence = "high" | "medium" | "low" | "insufficient";

export interface ValueEstimate {
  type: "private_sale" | "buyback" | "refurbished_retail" | "after_repair" | "original_retail";
  available: boolean;
  value: number | null;
  low: number | null;
  high: number | null;
  basis: string | null;
  basis_label: string | null;
  range_method: string | null;
  confidence: Confidence;
  observation_count: number;
  oldest_observation: string | null;
  newest_observation: string | null;
  sources: SourceRef[];
  reason: string | null;
}

export interface ValueTypes {
  buyback: ValueEstimate;
  refurbished_retail: ValueEstimate;
  original_retail: ValueEstimate;
}

export type OfferCondition = "new" | "refurbished" | "used";

export interface Offer {
  id: number;
  source: { id: string; name: string; verified: boolean; is_mock: boolean; automated: boolean; estimated?: boolean };
  title: string;
  brand: string | null;
  model_id: string | null;
  storage_gb: number | null;
  ram_gb: number | null;
  color: string | null;
  condition: OfferCondition;
  price_type: string;
  price: number;
  mrp: number | null;
  discount_pct: number | null;
  currency: Currency;
  url: string | null;
  seller: string | null;
  seller_type: string | null;
  availability: "in_stock" | "out_of_stock" | null;
  delivery_note: string | null;
  retrieved_at: string;
  published_at: string | null;
  freshness: "fresh" | "stale" | "expired" | "estimate";
  is_mock: boolean;
  match: { category: string; score: number; reasons: string[] };
}

export interface ProviderStatus {
  id: string;
  name: string;
  state: "operational" | "configured" | "failing" | "not_configured" | "manual_only";
  automated: boolean;
  markets: string;
  configured: boolean;
  requirement: string | null;
  last_job_status: string | null;
  last_job_message: string | null;
  last_retrieved_at: string | null;
  terms_note: string;
  docs_url: string | null;
}

export interface GroupSummary {
  count: number;
  lowest: number | null;
  highest: number | null;
  spread: number | null;
  sources: string[];
}

export type OfferGroup = "new" | "refurbished" | "used" | "buyback";

export interface MarketPrices {
  model_id: string;
  storage_gb: number;
  region: Region;
  currency: Currency;
  product: { id: string; manufacturer: string; name: string };
  groups: Record<OfferGroup, Offer[]>;
  summary: Record<OfferGroup, GroupSummary>;
  alternatives: Offer[];
  mrp: { value: number; count: number } | null;
  mock_data_included: boolean;
  estimates_included?: boolean;
  generated_at: string;
  fresh_hours: number;
  max_age_days: number;
  providers: ProviderStatus[];
}

export interface PriceHistory {
  model_id: string;
  storage_gb: number;
  region: Region;
  condition: OfferCondition;
  currency: Currency;
  days: number;
  observation_count: number;
  observed_days: number;
  available: boolean;
  mock_data_included: boolean;
  last_observation: string | null;
  series: Record<string, { date: string; lowest: number }[]>;
  lowest: { price: number; date: string } | null;
  highest: { price: number; date: string } | null;
  change: { from_date: string; to_date: string; amount: number; pct: number } | null;
  gaps: { from: string; to: string; days: number }[];
  reason: string | null;
}

export type Scope = "valuation:read" | "market_prices:read" | "price_history:read";

export interface Account {
  id: number;
  email: string;
  created_at: string;
  limits: { rate_limit_per_minute: number; daily_quota: number; max_keys: number };
  scopes_available: Scope[];
}

export interface ApiKey {
  id: number;
  name: string;
  prefix: string;
  scopes: Scope[];
  status: "active" | "revoked";
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  rate_limit_per_minute: number;
  daily_quota: number;
  requests_today: number;
  requests_30d: number;
}

export interface NewApiKey extends ApiKey {
  key: string;
}

export interface KeyUsage {
  key_id: number;
  days: number;
  total: number;
  by_day: { date: string; requests: number; errors: number }[];
  by_endpoint: Record<string, number>;
  by_status: Record<string, number>;
}

export interface WatchItem {
  id: number;
  model_id: string;
  product_name: string;
  storage_gb: number;
  region: Region;
  currency: Currency;
  condition: "new" | "refurbished";
  target_price: number | null;
  created_at: string;
  lowest_current_price: number | null;
  lowest_current_retrieved_at: string | null;
  unread_alerts: number;
}

export interface PriceAlert {
  id: number;
  watch_id: number;
  product_name: string;
  storage_gb: number;
  condition: string;
  price: number;
  currency: Currency;
  reason: string;
  source_name: string;
  url: string | null;
  is_mock: boolean;
  offer_retrieved_at: string;
  created_at: string;
  read: boolean;
}
