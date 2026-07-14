export type StageStatus = "complete" | "review_required" | "blocked" | "waiting";
export type DecisionAction = "approve_treatment" | "request_evidence" | "reject";
export type AdvisoryStatus = "not_requested" | "running" | "completed" | "unavailable" | "invalid";
export type AdvisoryProvider = "none" | "codex_session" | "codex_cli" | "chatgpt_manual" | "openai_api";

export interface Stage {
  number: number;
  id: string;
  title: string;
  status: StageStatus;
  status_label: string;
  owner: string;
  evidence_count: number;
  blocker: string | null;
  next_action: string;
  depends_on: string[];
}

export interface Citation {
  source_id: string;
  label: string;
  text: string;
  evidence_sha256: string;
}

export interface Calculation {
  currency: string;
  total_invoice_ore: number;
  service_start: string;
  service_end: string;
  service_days: number;
  period_start: string;
  period_end: string;
  current_period_days: number;
  current_period_expense_ore: number;
  prepaid_asset_ore: number;
  current_period_expense_label: string;
  prepaid_asset_label: string;
  formula: string;
  label: string;
  method: string;
}

export interface AdvisoryOutput {
  conclusion: string;
  rationale: string;
  citation_ids: string[];
  uncertainty: "low" | "medium" | "high";
  missing_evidence: string[];
  current_period_expense_ore: number;
  prepaid_asset_ore: number;
  cannot_approve: true;
}

export interface AdvisoryProvenance {
  transport: string | null;
  requested_model: string | null;
  reported_model: string | null;
  model_attestation: string | null;
  run_id: string | null;
  response_id: string | null;
  schema_validated: boolean;
  payload_sha256: string | null;
  controlled_display_sha256: string | null;
  evidence_snapshot_sha256: string | null;
}

export interface Advisory {
  status: AdvisoryStatus;
  provider: AdvisoryProvider;
  output: AdvisoryOutput | null;
  provenance: AdvisoryProvenance;
  safe_error_code: string | null;
}

export interface Decision {
  action: DecisionAction;
  label: string;
  rationale: string;
  actor_id: string;
  finding_id: string;
  snapshot_sha256: string;
  review_context_sha256: string;
  event_sequence: number;
  event_sha256: string;
  created_at: string;
  event_chain_valid: boolean;
  stale: boolean;
  accounting_action_performed: false;
  erp_write_performed: false;
}

export interface CloseProofCase {
  schema_version: "closeproof-case-v1";
  case_id: string;
  finding_id: string;
  entity: { id: string; name: string };
  period: { id: string; label: string };
  title: string;
  subtitle: string;
  outcome: string;
  selected_stage: string;
  stages: Stage[];
  checks: Array<{ id: string; label: string; status: string; result: string; calculated_by: string }>;
  finding: {
    title: string;
    amount_ore: number;
    amount_label: string;
    severity: string;
    summary: string;
    source: {
      document_id: string;
      supplier: string;
      invoice_date: string;
      page: number;
      line_range: string;
      citation: Citation;
    };
    calculation: Calculation;
    citations: Citation[];
  };
  evidence: { bundle_sha256: string; sources: Record<string, string> };
  snapshot_sha256: string;
  review_context_sha256: string;
  advisory: Advisory;
  decision: Decision | null;
  safety: {
    synthetic_only: true;
    sweden_first: true;
    erp_writes: false;
    model_authority: string;
    strip: string;
  };
}
