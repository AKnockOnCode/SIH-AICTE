// Hand-written shapes for nested records that the OpenAPI schema exposes as free-form objects.
// Top-level response types come from types.gen.ts (generated from the backend OpenAPI document).

export type * from "./types.gen";

export interface Bureau {
  code: string;
  name: string;
  kind: string;
  description: string;
}
export interface Region {
  code: string;
  name: string;
}
export interface StateRef {
  name: string;
  region_code: string;
}
export interface CategoryRule {
  code: string;
  label: string;
  description: string;
  family: string;
  severity_level: number;
  severity_weight: number;
  sla_days: number;
  default_bureau: string;
  active: number;
  sort_order: number;
  keywords?: string[];
  updated_at?: string;
  updated_by?: string;
}
export interface OfficerRef {
  id: string;
  display_name: string;
  designation: string;
  bureau_code: string;
  region_code: string | null;
}
export interface TrustRef {
  id: string;
  name: string;
  state: string;
}

export interface PriorityMixRow {
  band: string;
  n: number;
}
export interface RegionLoad {
  code: string;
  name: string;
  received: number;
  open_total: number;
  overdue: number;
}
export interface StateLoad {
  state: string;
  received: number;
  open_total: number;
  overdue: number;
}
export interface CategoryLoad {
  category_code: string;
  label: string;
  received: number;
  open_total: number;
  severity_level: number;
}
export interface CoordinationItem {
  id: string;
  tier: string;
  headline: string;
  score: number;
  status: string;
  recommended_lead: string | null;
  created_at: string;
  institution_id: string;
  institution_name: string;
  demo_tag: string | null;
  bureaus: string[];
}
export interface DashboardOverlaps {
  open_by_tier: Record<string, number>;
  cross_bureau_open: number;
  coordination_queue: CoordinationItem[];
}
export interface MultiBureauRow {
  institution_id: string;
  name: string;
  bureaus: number;
  codes: string[];
  open_cases: number;
}
export interface RecentAlert {
  id: string;
  alert_type: string;
  severity: string;
  title: string;
  case_id: string | null;
  institution_id: string | null;
  created_at: string;
  state: string;
}
export interface Triage {
  received: number;
  groups: Array<{ key: string; label: string; n: number }>;
  flows: Array<{ group: string; band: string; n: number }>;
  note: string;
}
export interface DemoLinks {
  institution_a: { id: string; name: string } | null;
  institution_a_conflict: string | null;
  live_trigger_institution: { id: string; name: string } | null;
  live_trigger_case: string | null;
  pending_match_reviews: number;
}

export interface InstitutionRecord {
  id: string;
  permanent_id: string | null;
  name: string;
  institution_type: string | null;
  address_line: string | null;
  city: string | null;
  district: string | null;
  state: string;
  region_code: string;
  pincode: string | null;
  established_year: number | null;
  intake_total: number | null;
  intake_source: string | null;
  trust_id: string | null;
  trust_relation_source: string | null;
  status: string;
  is_synthetic: number;
  demo_tag: string | null;
  courses: string[];
  provenance: Record<string, unknown> | null;
}
export interface AliasRow {
  alias: string;
  alias_type: string;
  source: string;
  created_at: string;
}
export interface TrustRecord {
  id: string;
  name: string;
  registration_ref: string | null;
  state: string | null;
  provenance: string;
  is_synthetic: number;
}
export interface SisterInstitution {
  id: string;
  name: string;
  state: string;
  district: string | null;
}
export interface InstitutionTimelineRow {
  case_id: string;
  action_type: string;
  action_at: string;
  actor_label: string;
  actor_role: string | null;
  bureau_code: string | null;
  remarks: string | null;
}
export interface InstitutionOverlap {
  id: string;
  tier: string;
  headline: string;
  status: string;
  score: number;
  recommended_lead: string | null;
  decided_lead: string | null;
  created_at: string;
  bureaus: string[];
  cases: string[];
}
export interface SignalBrief {
  id: string;
  signal_type: string;
  verification: string;
  title: string;
  publisher: string | null;
  source_url: string | null;
  published_date: string | null;
  match_status: string;
  match_confidence: number | null;
}
export interface MatchReviewBrief {
  id: string;
  raw_name: string;
  status: string;
  best_confidence: number | null;
  source_ref: string | null;
}
export interface MasterCaseBrief {
  id: string;
  kind: string;
  title: string;
  status: string;
  lead_bureau_code: string | null;
  created_at: string;
}

export interface MatchFactor {
  factor: string;
  label: string;
  effect: string;
}
export interface Candidate {
  institution_id: string;
  name: string;
  permanent_id: string | null;
  district: string | null;
  state: string | null;
  pincode: string | null;
  confidence: number;
  band: string;
  factors: MatchFactor[];
}
export interface MatchOutcome {
  query: { raw_name: string; normalized: string };
  candidates: Candidate[];
  decision: string;
  reason: string;
  thresholds: { auto_link: number; review: number };
  note: string;
}
export interface PairSignal {
  a: string;
  b: string;
  tier: string;
  score: number;
  rules: Array<{ code: string; text: string }>;
  text_similarity: number;
  days_apart: number;
  same_category: boolean;
  same_family: boolean;
  external_ref_match: boolean;
  cross_bureau: boolean;
  favourable_action: { case_id: string; action_type: string; action_at: string; bureau_code: string } | null;
}
export interface OpenCaseBrief {
  id: string;
  category_code: string;
  status: string;
  bureau_code: string;
  received_date: string;
  subject: string;
}
export interface LeadScore {
  bureau: string;
  bureau_name: string;
  subject_points: number;
  handler_points: number;
  action_points: number;
  open_cases: number;
  officers: number;
  open_per_officer: number;
  load_ratio: number;
  workload_factor: number;
  score: number;
  notes: string[];
}
export interface LeadRecommendation {
  recommended: string | null;
  recommended_name?: string;
  scores: LeadScore[];
  rationale: string[];
  advisory: boolean;
}
export interface GraphNode {
  key: string;
  kind: "institution" | "trust";
  id: string;
  label: string;
  state: string;
  district?: string | null;
  region?: string;
  risk?: number | null;
  risk_band?: string | null;
  trend?: string | null;
  open_cases: number;
  overdue: number;
  total_cases?: number;
  open_bureaus?: number;
  open_overlaps?: number;
  conflicts?: number;
  flagged: boolean;
  flag_reasons?: string[];
  demo_tag?: string | null;
  synthetic: boolean;
  provenance?: string;
  members?: number;
  flagged_members?: number;
  avg_risk?: number | null;
  max_risk?: number | null;
  patterns?: string[];
}
export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  provenance: string;
}
export interface GraphGroup {
  trust_id: string;
  name: string;
  members: number;
  flagged_members: number;
  open_cases: number;
  overdue: number;
  avg_risk: number | null;
  max_risk: number | null;
  states: string[];
  patterns: string[];
  provenance: string;
  institutions: string[];
}
