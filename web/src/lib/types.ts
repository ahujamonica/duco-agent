export interface User {
  id: number;
  name: string;
  email: string;
  locale: string;
}

export interface MemberLink {
  policy_id: number;
  insurer: string;
  plan_name: string;
  role: string;
}

export interface Member {
  id: number;
  family_id: number;
  name: string;
  date_of_birth: string | null;
  age: number | null;
  relation: string;
  gender: string | null;
  phone: string | null;
  notes: string | null;
  policies: MemberLink[];
}

export interface Terms {
  sum_insured: string;
  deductible: string;
  deductible_used: string;
  coinsurance_member: string;
  oop_max: string;
  oop_used: string;
  annual_limit: string;
  annual_limit_used: string;
  preauth_threshold: string;
  preauth_penalty_rate: string;
  waiting_period_days: number;
  allowed_factor: string;
  network_only: boolean;
  preauth_always: boolean;
  covers_primary_exclusions: boolean;
  sublimits: any[];
  exclusions: any[];
  preauth_cpt_codes: string[];
  preauth_categories: string[];
}

export interface PolicyVersion {
  id: number;
  version: number;
  effective_from: string | null;
  terms: Terms;
  source: string;
  confirmed: boolean;
  change_note: string | null;
  created_at: string | null;
  extraction: Record<string, any>;
}

export interface Policy {
  id: number;
  family_id: number;
  insurer_name: string;
  plan_name: string;
  policy_number: string;
  policyholder_member_id: number | null;
  policyholder_name: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
  coordination_rule: string;
  created_at: string | null;
  current_version: PolicyVersion | null;
  members: { member_id: number; name: string; role: string; relation?: string }[];
  version_count: number;
  versions?: PolicyVersion[];
}

export interface Family {
  id: number;
  name: string;
  coordination_rule: string;
  notes: string | null;
  created_at: string;
  members: Member[];
  policies: Policy[];
  counts: { members: number; policies: number; documents: number; cases: number };
  cases: {
    id: number;
    title: string;
    status: string;
    patient_member_id?: number;
    claim_count?: number;
    procedure_count?: number;
    adjudication_count?: number;
    totals: any;
    created_at: string;
  }[];
  documents?: DocumentItem[];
}

export interface DocField {
  value: any;
  confidence: number;
  source: string;
  evidence: string;
  status: "ok" | "review" | "missing";
}

export interface DocumentLine {
  description: string;
  amount: string | null;
  quantity: number | null;
  unit_rate: string | null;
  cpt_code: string | null;
  icd_codes: string[];
  category: string;
  confidence: number;
  code_source: string;
  code_confidence: number;
  evidence: string;
  issues: string[];
}

export interface DocumentItem {
  id: number;
  family_id: number;
  filename: string;
  mime: string;
  size_bytes: number;
  doc_type: string;
  classification_confidence: number;
  classification_evidence: string[];
  status: string;
  method: string;
  pages: number;
  mean_ocr_confidence: number | null;
  issues: string[];
  created_at: string;
  confirmed_at: string | null;
  lines: DocumentLine[];
  field_count: number;
  fields?: Record<string, DocField>;
  duplicate?: boolean;
}

export interface ReviewItem {
  id: number;
  case_id: number;
  document_id: number | null;
  field_key: string;
  label: string;
  extracted_value: string | null;
  confidence: number;
  source_text: string | null;
  reason: string | null;
  status: "pending" | "accepted" | "corrected";
  corrected_value: string | null;
}

export interface CaseClaimLine {
  id: number;
  description: string;
  quantity: number | null;
  unit_rate: string | null;
  billed: string;
  cpt_code: string | null;
  category: string;
  icd_codes: string[];
  code_source: string;
  code_confidence: number;
}

export interface CaseDetail {
  id: number;
  family_id: number;
  title: string;
  status: string;
  patient_member_id: number;
  selected_member_ids: number[];
  provider_name: string;
  provider_in_network: boolean;
  service_date: string | null;
  narrative: string | null;
  coordination_rule: string;
  policy_version_ids: number[];
  document_ids: number[];
  review_confirmed: boolean;
  totals: Record<string, string | number>;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  family: { id: number; name: string; coordination_rule: string } | null;
  patient: Member | null;
  claims: {
    id: number;
    patient: string;
    member_id: number | null;
    provider: string;
    service_date: string | null;
    bill_number: string | null;
    document_id: number | null;
    line_count: number;
    billed: string;
    lines: CaseClaimLine[];
  }[];
  documents: DocumentItem[];
  policies: Policy[];
  review_items: ReviewItem[];
  review_pending: number;
  gaps: { code: string; severity: string; title: string; detail: string; action?: string }[];
  assumptions: string[];
  trace: { events: number; stage: string; tasks: Record<string, string> };
}

export interface TraceEvent {
  seq: number;
  agent: string;
  goal: string;
  state: string;
  action: string;
  tool: string | null;
  inputs: Record<string, any>;
  observation: string;
  checks: { name: string; passed: boolean; detail: string }[];
  decision: string;
  next_action: string | null;
  status: string;
  started_at: string;
  duration_ms: number | null;
  run_id: string;
}

export interface TraceResponse {
  case_id: number;
  status: string;
  run_id: string | null;
  stage: string | null;
  tasks: Record<string, string>;
  events: TraceEvent[];
  last_seq: number;
  simulated: boolean;
}

export interface LinePlan {
  plan_key: string;
  role: string;
  order: number;
  base: string;
  excluded: string;
  sublimit_excess: string;
  allowed: string;
  contractual: string;
  deductible: string;
  coinsurance: string;
  penalty: string;
  oop_cap: string;
  plan_paid: string;
  member_covered: string;
  annual_limit_excess: string;
  member_total: string;
  eligible: boolean;
  notes: string[];
}

export interface ResultLine {
  id: number;
  description: string;
  cpt_code: string | null;
  category: string;
  billed: string;
  allowed: string;
  contractual: string;
  excluded: string;
  patient: string;
  patient_parts: Record<string, string>;
  plans: LinePlan[];
  notes: string[];
}

export interface ResultClaim {
  id: number;
  patient: string;
  member_id: number | null;
  provider: string;
  service_date: string | null;
  bill_number: string | null;
  document_id: number | null;
  totals: Record<string, string>;
  order: { plan_key: string; role: string; order: number; rule: string; evidence: string[]; assumption: string | null }[];
  plans: any[];
  lines: ResultLine[];
  warnings: string[];
  assumptions: string[];
  invariants: { name: string; passed: boolean; detail: string }[];
}

export interface Results {
  case: {
    id: number;
    title: string;
    status: string;
    family?: string;
    provider?: string;
    service_date?: string;
    coordination_rule?: string;
    totals?: Record<string, string>;
  };
  totals: Record<string, string>;
  claims: ResultClaim[];
  accumulators: any[];
  preauth: any[];
  eligibility: any[];
  gaps: { code: string; severity: string; title: string; detail: string; action?: string }[];
  assumptions: string[];
  savings: { claim_id: number; without_coordination: string; with_coordination: string; saving: string }[];
  invariants: any[];
  reports: { id: number; kind: string; title: string; mime: string; meta: any; created_at: string }[];
  audit: { events: number; adjudications: number; api_calls: number; simulated: boolean };
  disclaimer: string;
}

export interface ReportItem {
  id: number;
  kind: string;
  title: string;
  mime: string;
  meta: Record<string, any>;
  created_at: string;
  size_bytes?: number;
}

export interface DashboardData {
  totals: {
    cases: number;
    families: number;
    active_claims: number;
    pending_authorizations: number;
    billed: string;
    insurer_paid: string;
    primary_paid: string;
    secondary_paid: string;
    patient_responsibility: string;
  };
  recent_cases: {
    id: number;
    title: string;
    status: string;
    family: string | null;
    provider: string;
    service_date: string | null;
    totals: Record<string, string | number>;
    updated_at: string;
  }[];
  attention: { case_id: number; title: string; status: string; detail: string }[];
  simulated: boolean;
}
