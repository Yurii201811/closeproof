import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Advisory, CloseProofCase, StageStatus } from "./types";

const emptyProvenance = {
  transport: null,
  requested_model: null,
  reported_model: null,
  model_attestation: null,
  run_id: null,
  response_id: null,
  schema_validated: false,
  payload_sha256: null,
  controlled_display_sha256: null,
  evidence_snapshot_sha256: null,
};

const caseData: CloseProofCase = {
  schema_version: "closeproof-case-v1",
  case_id: "case-1",
  finding_id: "finding-1",
  entity: { id: "nordix", name: "Nordix Services AB" },
  period: { id: "2026-06", label: "June 2026" },
  title: "June close — Review required",
  subtitle: "Evidence-linked controller review",
  outcome: "review_required",
  selected_stage: "adjustments",
  stages: [
    [1, "evidence_completeness", "Evidence completeness", "complete", "Verified"],
    [2, "bank_reconciliation", "Bank reconciliation", "complete", "Verified"],
    [3, "subledgers", "Subledgers", "complete", "Verified"],
    [4, "adjustments", "Adjustments", "review_required", "Review required"],
    [5, "balanced_trial_balance", "Balanced trial balance", "waiting", "Waiting on Adjustments"],
    [6, "vat_control", "VAT control", "waiting", "Waiting on Adjustments"],
    [7, "preparer_review", "Preparer review", "waiting", "Waiting on Adjustments"],
    [8, "independent_signoff", "Independent sign-off", "waiting", "Waiting on Adjustments"],
    [9, "lock_readiness", "Lock readiness", "waiting", "Waiting on Adjustments"],
  ].map(([number, id, title, status, status_label]) => ({
    number: number as number,
    id: id as string,
    title: title as string,
    status: status as StageStatus,
    status_label: status_label as string,
    owner: "A. Reviewer",
    evidence_count: number as number,
    blocker: id === "adjustments" ? "Annual software invoice spans 12 months" : status === "waiting" ? "Waiting on Adjustments" : null,
    next_action: status === "waiting" ? "Await completion of Adjustments" : "No action",
    depends_on: [],
  })),
  checks: [],
  finding: {
    title: "Prepaid service period",
    amount_ore: 12000000,
    amount_label: "SEK 120,000.00",
    severity: "review_required",
    summary: "Annual software invoice spans 12 months.",
    source: {
      document_id: "INV-4821",
      supplier: "CloudWorks AB",
      invoice_date: "2026-06-15",
      page: 1,
      line_range: "L8",
      citation: { source_id: "INV-4821:p1:L8", label: "Invoice", text: "Service period", evidence_sha256: "a".repeat(64) },
    },
    calculation: {
      currency: "SEK",
      total_invoice_ore: 12000000,
      service_start: "2026-06-15",
      service_end: "2027-06-14",
      service_days: 365,
      period_start: "2026-06-01",
      period_end: "2026-06-30",
      current_period_days: 16,
      current_period_expense_ore: 526027,
      prepaid_asset_ore: 11473973,
      current_period_expense_label: "SEK 5,260.27",
      prepaid_asset_label: "SEK 114,739.73",
      formula: "12000000 × 16 ÷ 365",
      label: "Calculated by controls",
      method: "inclusive_daily_allocation",
    },
    citations: [],
  },
  evidence: { bundle_sha256: "b".repeat(64), sources: {} },
  snapshot_sha256: "c".repeat(64),
  review_context_sha256: "e".repeat(64),
  advisory: {
    status: "not_requested",
    provider: "none",
    output: null,
    provenance: emptyProvenance,
    safe_error_code: null,
  },
  decision: null,
  safety: {
    synthetic_only: true,
    sweden_first: true,
    erp_writes: false,
    model_authority: "advisory_only",
    strip: "legacy backend copy is not rendered",
  },
};

function apiMock(data: CloseProofCase, overrides: Record<string, { ok: boolean; status?: number; json: () => Promise<unknown> }> = {}) {
  return vi.fn().mockImplementation(async (input: string | URL | Request) => {
    const path = String(input);
    if (overrides[path]) return overrides[path];
    if (path === "/api/session") return { ok: true, status: 200, json: async () => ({ csrf_token: "csrf-test-token" }) };
    if (path === "/api/case") return { ok: true, status: 200, json: async () => data };
    throw new Error(`Unexpected request: ${path}`);
  });
}

function withAdvisory(advisory: Advisory): CloseProofCase {
  return { ...caseData, advisory };
}

describe("CloseProof reviewer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", apiMock(caseData));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("renders the canonical stages in order with explicit accessible statuses", async () => {
    render(<App />);
    const ledger = await screen.findByRole("heading", { name: "Nine-stage close dependency ledger" });
    const list = ledger.parentElement!.querySelector("ol")!;
    const rows = within(list).getAllByRole("listitem");
    const buttons = within(list).getAllByRole("button");

    expect(rows).toHaveLength(9);
    expect(within(rows[0]).getByText("Evidence completeness")).toBeInTheDocument();
    expect(within(rows[8]).getByText("Lock readiness")).toBeInTheDocument();
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveAccessibleName(/4\. Adjustments\. Review required/);
    expect(screen.getByRole("link", { name: "Close workflow" })).toHaveAttribute("href", "#close-ledger");
    expect(screen.getByRole("button", { name: /Review queue/ })).toBeDisabled();
  });

  it("renders proof content from the authoritative case instead of golden-case literals", async () => {
    const sentinel: CloseProofCase = {
      ...caseData,
      entity: { id: "sentinel", name: "Sentinel Entity AS" },
      period: { id: "2031-02", label: "February 2031" },
      title: "Sentinel close — Review required",
      stages: caseData.stages.map((stage) => stage.id === "adjustments"
        ? { ...stage, blocker: "Sentinel blocker from case data" }
        : stage.id === "balanced_trial_balance"
          ? { ...stage, status: "review_required", status_label: "Review required" }
          : stage),
      finding: {
        ...caseData.finding,
        amount_label: "NOK 98,765.00",
        source: {
          document_id: "DOC-9",
          supplier: "Sentinel Supplier AS",
          invoice_date: "2031-02-02",
          page: 7,
          line_range: "L99",
          citation: {
            source_id: "DOC-9:p7:L99",
            label: "Sentinel evidence",
            text: "Sentinel evidence excerpt from the authoritative case",
            evidence_sha256: "9".repeat(64),
          },
        },
        calculation: {
          ...caseData.finding.calculation,
          total_invoice_ore: 9876500,
          service_start: "2031-02-02",
          service_end: "2031-03-15",
          service_days: 42,
          period_start: "2031-02-01",
          period_end: "2031-02-10",
          current_period_days: 9,
          current_period_expense_label: "NOK 21,164.64",
          prepaid_asset_label: "NOK 77,600.36",
          formula: "9876500 × 9 ÷ 42",
        },
      },
    };
    vi.stubGlobal("fetch", apiMock(sentinel));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Sentinel close — Review required" })).toBeInTheDocument();
    expect(screen.getByLabelText("2 exceptions require review")).toBeInTheDocument();
    expect(screen.getAllByText("Sentinel blocker from case data").length).toBeGreaterThan(0);
    expect(screen.getByText("DOC-9 · page 7 · L99")).toBeInTheDocument();
    expect(screen.getByText("Sentinel evidence excerpt from the authoritative case")).toBeInTheDocument();
    expect(screen.getByText("2 Feb 2031 → 15 Mar 2031")).toBeInTheDocument();
    expect(screen.getByText("98,765 × 9 ÷ 42")).toBeInTheDocument();
    expect(screen.getByText("98,765.00 − 21,164.64")).toBeInTheDocument();
  });

  it("fails closed when the stage ledger is empty", async () => {
    vi.stubGlobal("fetch", apiMock({ ...caseData, stages: [] }));

    render(<App />);

    expect(await screen.findByText("No close stages are available")).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: /Prepaid service period/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Human rationale/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Continue to human rationale/ })).not.toBeInTheDocument();
  });

  it("shows source, deterministic, optional advisory, and human layers without merging authority", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: /Prepaid service period/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Source evidence/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Deterministic allocation/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Model advisory/ })).toBeInTheDocument();
    expect(screen.getByText("Advisory — cannot approve")).toBeInTheDocument();
    expect(screen.getByText("Not requested")).toBeInTheDocument();
    expect(screen.getByText("No provider")).toBeInTheDocument();
    expect(screen.getByText("SEK 5,260.27")).toBeInTheDocument();
    expect(screen.getByText("SEK 114,739.73")).toBeInTheDocument();
    expect(screen.getByText("Synthetic demo · Local controls · No ERP writes · Advisory optional")).toBeInTheDocument();
    expect(screen.queryByText(/GPT-5\.6|Fixture preview/i)).not.toBeInTheDocument();
  });

  it.each([
    ["not_requested", "none", "Not requested"],
    ["running", "codex_session", "Running"],
    ["completed", "openai_api", "Completed"],
    ["unavailable", "codex_cli", "Unavailable"],
    ["invalid", "openai_api", "Invalid"],
  ] as const)("renders the %s advisory state with a visible non-color label", async (status, provider, label) => {
    const completedOutput = status === "completed" ? {
      conclusion: "Use the deterministic allocation, subject to human review.",
      rationale: "The cited service period crosses the close date.",
      citation_ids: ["INV-4821:p1:L8"],
      uncertainty: "low" as const,
      missing_evidence: [],
      current_period_expense_ore: 526027,
      prepaid_asset_ore: 11473973,
      cannot_approve: true as const,
    } : null;
    vi.stubGlobal("fetch", apiMock(withAdvisory({
      status,
      provider,
      output: completedOutput,
      provenance: { ...emptyProvenance, schema_validated: status === "completed", transport: provider === "none" ? null : provider },
      safe_error_code: status === "invalid" ? "ADVISORY_SCHEMA_INVALID" : null,
    })));

    render(<App />);

    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByLabelText(/Provider:/)).toBeInTheDocument();
    if (status === "completed") {
      expect(screen.getByText(/Controlled display generated locally/)).toBeInTheDocument();
    }
  });

  it.each([
    ["codex_session", "Codex requested · Validated output"],
    ["codex_cli", "Codex requested · Validated output"],
    ["chatgpt_manual", "Manual import · Unverified model identity"],
    ["openai_api", "API response · Verified"],
  ] as const)("presents %s provenance truthfully", async (provider, assurance) => {
    vi.stubGlobal("fetch", apiMock(withAdvisory({
      status: "completed",
      provider,
      output: {
        conclusion: "Use the deterministic allocation, subject to human review.",
        rationale: "The cited service period crosses the close date.",
        citation_ids: ["INV-4821:p1:L8"],
        uncertainty: "low",
        missing_evidence: [],
        current_period_expense_ore: 526027,
        prepaid_asset_ore: 11473973,
        cannot_approve: true,
      },
      provenance: {
        ...emptyProvenance,
        transport: provider,
        requested_model: "requested-model",
        reported_model: "reported-model",
        model_attestation: "matched",
        schema_validated: true,
      },
      safe_error_code: null,
    })));

    render(<App />);

    expect(await screen.findByText(assurance)).toBeInTheDocument();
    expect(screen.getByText("Provider provenance")).toBeInTheDocument();
  });

  it.each([
    ["codex_cli", "Codex route · No validated output"],
    ["openai_api", "API route · No validated response"],
  ] as const)("does not imply that a failed %s route returned output", async (provider, assurance) => {
    vi.stubGlobal("fetch", apiMock(withAdvisory({
      status: "unavailable",
      provider,
      output: null,
      provenance: { ...emptyProvenance, transport: provider === "codex_cli" ? "codex_cli_chatgpt" : "responses_api", requested_model: provider === "codex_cli" ? "gpt-5.6-sol" : "gpt-5.6" },
      safe_error_code: provider === "codex_cli" ? "codex_unavailable" : "openai_api_key_required",
    })));

    render(<App />);

    expect(await screen.findByText(assurance)).toBeInTheDocument();
  });

  it("opens a focus-contained mobile proof dialog and returns focus when closed", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      media: "(max-width: 1279px)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    } as unknown as MediaQueryList));
    render(<App />);
    const adjustment = await screen.findByRole("button", { name: /4\. Adjustments\. Review required/ });

    await user.click(adjustment);

    expect(screen.getByRole("dialog", { name: /Prepaid service period/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Close proof sheet" })).toHaveFocus());
    expect(screen.getByRole("main")).toHaveAttribute("inert");
    expect(document.documentElement.style.overflow).toBe("hidden");

    await user.click(screen.getByRole("button", { name: "Close proof sheet" }));

    await waitFor(() => expect(adjustment).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.documentElement.style.overflow).toBe("");
  });

  it("guides the reviewer to rationale before recording the bound decision", async () => {
    const user = userEvent.setup();
    const decision = {
      action: "approve_treatment",
      label: "Treatment approved for workpaper",
      rationale: "The exact allocation agrees with evidence.",
      actor_id: "demo-controller",
      finding_id: "finding-1",
      snapshot_sha256: "c".repeat(64),
      review_context_sha256: "e".repeat(64),
      event_sequence: 1,
      event_sha256: "d".repeat(64),
      created_at: "2026-07-13T12:00:00+00:00",
      event_chain_valid: true,
      stale: false,
      accounting_action_performed: false,
      erp_write_performed: false,
    };
    const fetchMock = apiMock(caseData, {
      "/api/decisions": { ok: true, status: 200, json: async () => ({ decision, case: { ...caseData, decision } }) },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const continueToRationale = await screen.findByRole("button", { name: /Continue to human rationale/ });
    const rationale = screen.getByLabelText(/Human rationale/);

    expect(screen.queryByRole("button", { name: /Approve treatment/ })).not.toBeInTheDocument();
    await user.click(continueToRationale);
    expect(rationale).toHaveFocus();
    await user.type(rationale, "The exact allocation agrees with the cited evidence and policy.");
    const approve = screen.getByRole("button", { name: /Approve treatment/ });
    expect(approve).toBeEnabled();
    await user.click(approve);

    await waitFor(() => expect(screen.getByText("Treatment approved for workpaper")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "June close — Decision recorded" })).toBeInTheDocument();
    expect(screen.getByLabelText("1 human decision recorded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /4\. Adjustments\. Decision recorded/ })).toBeInTheDocument();
    expect(screen.getByText(/Remaining close stages are outside this focused demo/)).toBeInTheDocument();
    expect(screen.queryByText(/remain waiting until the evidence-bound Adjustments decision is recorded/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download validated workpaper" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download validated workpaper" })).toHaveFocus();
    expect(rationale).toHaveValue(decision.rationale);
    expect(rationale).toHaveAttribute("readonly");
    expect(screen.getByText(/This recorded rationale is read-only/)).toBeInTheDocument();
    const decisionCall = fetchMock.mock.calls.find(([url]) => url === "/api/decisions");
    expect(decisionCall?.[1]).toMatchObject({ headers: expect.objectContaining({ "X-CloseProof-CSRF": "csrf-test-token" }) });
    expect(JSON.parse(String(decisionCall?.[1]?.body))).toMatchObject({ review_context_sha256: "e".repeat(64) });
  });

  it.each([
    ["request_evidence", "Request evidence", "Additional evidence requested", "Evidence requested", "Waiting on evidence", "evidence request is recorded"],
    ["reject", "Reject", "Proposed treatment rejected", "Treatment rejected", "Waiting on revised treatment", "rejection is recorded"],
  ] as const)("presents the recorded %s outcome consistently", async (action, buttonLabel, label, titleState, downstreamState, note) => {
    const user = userEvent.setup();
    const decision = {
      action,
      label,
      rationale: "The evidence-bound review supports this recorded human outcome.",
      actor_id: "demo-controller",
      finding_id: "finding-1",
      snapshot_sha256: "c".repeat(64),
      review_context_sha256: "e".repeat(64),
      event_sequence: 1,
      event_sha256: "d".repeat(64),
      created_at: "2026-07-13T12:00:00+00:00",
      event_chain_valid: true,
      stale: false,
      accounting_action_performed: false,
      erp_write_performed: false,
    };
    vi.stubGlobal("fetch", apiMock(caseData, {
      "/api/decisions": { ok: true, status: 200, json: async () => ({ decision, case: { ...caseData, decision } }) },
    }));
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /Continue to human rationale/ }));
    await user.type(screen.getByLabelText(/Human rationale/), decision.rationale);
    await user.click(screen.getByRole("button", { name: buttonLabel }));

    expect(await screen.findByRole("heading", { name: `June close — ${titleState}` })).toBeInTheDocument();
    expect(screen.getByLabelText("1 human decision recorded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(`4\\. Adjustments\\. ${titleState}`) })).toBeInTheDocument();
    expect(screen.getAllByText(downstreamState).length).toBeGreaterThan(0);
    expect(screen.getByText(new RegExp(note, "i"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download validated workpaper" })).toHaveFocus();
  });

  it("copies a server-built prompt and imports a manual result with CSRF", async () => {
    const user = userEvent.setup();
    const imported: Advisory = {
      status: "completed",
      provider: "chatgpt_manual",
      output: {
        conclusion: "Use the exact allocation, subject to human review.",
        rationale: "The cited annual service period crosses the close date.",
        citation_ids: ["INV-4821:p1:L8"],
        uncertainty: "low",
        missing_evidence: [],
        current_period_expense_ore: 526027,
        prepaid_asset_ore: 11473973,
        cannot_approve: true,
      },
      provenance: { ...emptyProvenance, transport: "manual", reported_model: "reported-model", schema_validated: true },
      safe_error_code: null,
    };
    const fetchMock = apiMock(caseData, {
      "/api/advisory/prompt": { ok: true, status: 200, json: async () => ({ prompt: "Evidence-bound prompt" }) },
      "/api/advisory/import": {
        ok: true,
        status: 200,
        json: async () => ({ case: { ...caseData, advisory: imported, review_context_sha256: "f".repeat(64) } }),
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const copy = await screen.findByRole("button", { name: "Copy prompt" });
    const clipboard = vi.spyOn(navigator.clipboard, "writeText");

    await user.click(copy);
    await waitFor(() => expect(clipboard).toHaveBeenCalledWith("Evidence-bound prompt"));
    await user.click(screen.getByText("Paste manual result"));
    await user.click(screen.getByLabelText("Advisory JSON"));
    await user.paste(JSON.stringify({ conclusion: "Use exact allocation" }));
    await user.type(screen.getByLabelText(/Reported model/), "reported-model");
    await user.click(screen.getByRole("button", { name: "Import advisory" }));

    expect(await screen.findByText("Manual import · Unverified model identity")).toBeInTheDocument();
    expect(screen.getByLabelText(/Human rationale/)).toHaveFocus();
    const importCall = fetchMock.mock.calls.find(([url]) => url === "/api/advisory/import");
    expect(importCall?.[1]).toMatchObject({ headers: expect.objectContaining({ "X-CloseProof-CSRF": "csrf-test-token" }) });
    expect(JSON.parse(String(importCall?.[1]?.body))).toEqual({ payload: { conclusion: "Use exact allocation" }, reported_model: "reported-model" });
  });

  it("recovers when clipboard access hangs and exposes the prepared prompt", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", apiMock(caseData, {
      "/api/advisory/prompt": { ok: true, status: 200, json: async () => ({ prompt: "Evidence-bound prompt" }) },
    }));
    vi.spyOn(navigator.clipboard, "writeText").mockImplementation(() => new Promise<void>(() => undefined));
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Copy prompt" }));

    expect(await screen.findByText(/Automatic clipboard access was unavailable/, {}, { timeout: 2_500 })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Evidence-bound prompt" })).toHaveValue("Evidence-bound prompt");
    expect(screen.getByRole("button", { name: "Retry copy" })).toBeEnabled();
  });

  it("explains a fail-closed manual model mismatch", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", apiMock(caseData, {
      "/api/advisory/import": {
        ok: false,
        status: 422,
        json: async () => ({ error: "model_mismatch" }),
      },
    }));
    render(<App />);

    await user.click(await screen.findByText("Paste manual result"));
    await user.click(screen.getByLabelText("Advisory JSON"));
    await user.paste(JSON.stringify({ conclusion: "Structured result" }));
    await user.type(screen.getByLabelText(/Reported model/), "ChatGPT subscription response");
    await user.click(screen.getByRole("button", { name: "Import advisory" }));

    expect(await screen.findByText(/optional reported model did not match GPT-5\.6/i)).toBeInTheDocument();
    expect(screen.getByText(/leave the field blank unless ChatGPT explicitly reports its model/i)).toBeInTheDocument();
  });

  it("unlocks review and suppresses export when an advisory stales the prior decision", async () => {
    const user = userEvent.setup();
    const previousDecision = {
      action: "approve_treatment" as const,
      label: "Treatment approved for workpaper",
      rationale: "The exact allocation agrees with the cited evidence and policy.",
      actor_id: "demo-controller",
      finding_id: "finding-1",
      snapshot_sha256: "c".repeat(64),
      review_context_sha256: "e".repeat(64),
      event_sequence: 1,
      event_sha256: "d".repeat(64),
      created_at: "2026-07-13T12:00:00+00:00",
      event_chain_valid: true,
      stale: false,
      accounting_action_performed: false as const,
      erp_write_performed: false as const,
    };
    const initial = { ...caseData, decision: previousDecision };
    const stale = { ...previousDecision, stale: true };
    const imported: Advisory = {
      ...caseData.advisory,
      status: "completed",
      provider: "chatgpt_manual",
      output: {
        conclusion: "Use the deterministic allocation, subject to human review.",
        rationale: "The cited annual service period crosses the close date and agrees with the local control.",
        citation_ids: ["INV-4821:p1:L8"],
        uncertainty: "low",
        missing_evidence: [],
        current_period_expense_ore: 526027,
        prepaid_asset_ore: 11473973,
        cannot_approve: true,
      },
    };
    vi.stubGlobal("fetch", apiMock(initial, {
      "/api/advisory/import": {
        ok: true,
        status: 200,
        json: async () => ({ case: { ...initial, advisory: imported, decision: stale, review_context_sha256: "f".repeat(64) } }),
      },
    }));
    render(<App />);

    await user.click(await screen.findByText("Paste manual result"));
    await user.click(screen.getByLabelText("Advisory JSON"));
    await user.paste(JSON.stringify({ conclusion: "Use exact allocation" }));
    await user.click(screen.getByRole("button", { name: "Import advisory" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Previous decision is stale");
    await waitFor(() => expect(screen.getByLabelText(/Human rationale/)).toHaveValue(""));
    expect(screen.queryByRole("button", { name: /Download validated workpaper/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve treatment/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Continue to human rationale/ })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Human rationale/), "The updated advisory and exact controls support a fresh human review.");
    expect(screen.getByRole("button", { name: /Approve treatment/ })).toBeEnabled();
    expect(screen.getByText("Rationale ready. Choose one human action.")).toBeInTheDocument();
  });

  it("blocks export and further actions when decision-chain integrity fails", async () => {
    const corruptedDecision = {
      action: "approve_treatment" as const,
      label: "Treatment approved for workpaper",
      rationale: "The exact allocation agrees with the cited evidence and policy.",
      actor_id: "demo-controller",
      finding_id: "finding-1",
      snapshot_sha256: "c".repeat(64),
      review_context_sha256: "e".repeat(64),
      event_sequence: 1,
      event_sha256: "d".repeat(64),
      created_at: "2026-07-13T12:00:00+00:00",
      event_chain_valid: false,
      stale: false,
      accounting_action_performed: false as const,
      erp_write_performed: false as const,
    };
    vi.stubGlobal("fetch", apiMock({ ...caseData, decision: corruptedDecision }));
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Decision chain integrity failed");
    expect(screen.queryByText(/local hash chain consistent/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download validated workpaper/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve treatment/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Continue to human rationale/ })).not.toBeInTheDocument();
  });

  it("downloads only a workpaper that matches the active evidence and verified event", async () => {
    const user = userEvent.setup();
    const decision = {
      action: "approve_treatment" as const,
      label: "Treatment approved for workpaper",
      rationale: "The exact allocation agrees with the cited evidence and policy.",
      actor_id: "demo-controller",
      finding_id: "finding-1",
      snapshot_sha256: "c".repeat(64),
      review_context_sha256: "e".repeat(64),
      event_sequence: 1,
      event_sha256: "d".repeat(64),
      created_at: "2026-07-14T07:56:50+00:00",
      event_chain_valid: true,
      stale: false,
      accounting_action_performed: false as const,
      erp_write_performed: false as const,
    };
    const workpaper = {
      schema_version: "closeproof-workpaper-v1",
      snapshot_sha256: caseData.snapshot_sha256,
      review_context_sha256: caseData.review_context_sha256,
      human_decision: decision,
      event_chain: {
        valid: true,
        semantic_validation_scope: "current_decision",
        semantically_validated_event_sequence: decision.event_sequence,
        semantically_validated_event_sha256: decision.event_sha256,
      },
      external_actions_performed: [],
    };
    const createObjectURL = vi.fn(() => "blob:closeproof-workpaper");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", apiMock({ ...caseData, decision }, {
      "/api/workpaper": { ok: true, status: 200, json: async () => workpaper },
    }));

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Download validated workpaper" }));

    expect(await screen.findByText("Validated workpaper downloaded. No accounting or ERP action occurred.")).toBeInTheDocument();
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(anchorClick).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:closeproof-workpaper");
    anchorClick.mockRestore();
    delete (URL as unknown as Record<string, unknown>).createObjectURL;
    delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
  });

  it("fails closed when the exported workpaper does not match the active evidence", async () => {
    const user = userEvent.setup();
    const decision = {
      action: "approve_treatment" as const,
      label: "Treatment approved for workpaper",
      rationale: "The exact allocation agrees with the cited evidence and policy.",
      actor_id: "demo-controller",
      finding_id: "finding-1",
      snapshot_sha256: "c".repeat(64),
      review_context_sha256: "e".repeat(64),
      event_sequence: 1,
      event_sha256: "d".repeat(64),
      created_at: "2026-07-14T07:56:50+00:00",
      event_chain_valid: true,
      stale: false,
      accounting_action_performed: false as const,
      erp_write_performed: false as const,
    };
    vi.stubGlobal("fetch", apiMock({ ...caseData, decision }, {
      "/api/workpaper": {
        ok: true,
        status: 200,
        json: async () => ({
          schema_version: "closeproof-workpaper-v1",
          snapshot_sha256: "0".repeat(64),
          review_context_sha256: caseData.review_context_sha256,
          human_decision: decision,
          event_chain: { valid: true },
          external_actions_performed: [],
        }),
      },
    }));

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Download validated workpaper" }));

    expect(await screen.findByText("The downloaded workpaper failed CloseProof integrity checks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download validated workpaper" })).toBeInTheDocument();
  });

  it.each(["running", "invalid"] as const)("keeps manual import available for a %s manual advisory", async (status) => {
    vi.stubGlobal("fetch", apiMock(withAdvisory({
      status,
      provider: "chatgpt_manual",
      output: null,
      provenance: { ...emptyProvenance, transport: "manual_import", requested_model: "gpt-5.6" },
      safe_error_code: status === "invalid" ? "invalid_import" : null,
    })));
    render(<App />);

    expect(await screen.findByText("Paste manual result")).toBeInTheDocument();
    if (status === "running") {
      expect(screen.getByText(/Prompt prepared locally; no provider was contacted/)).toBeInTheDocument();
    }
  });

  it("renders a recoverable server error state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Loopback unavailable")));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "The evidence case could not be loaded" })).toBeInTheDocument();
    expect(screen.getByText("Loopback unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry case load" })).toBeInTheDocument();
  });

  it("has no automated accessibility violations in the primary review state", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "June close — Review required" });

    const results = await axe(document.body);

    expect(results.violations).toEqual([]);
  });

  it("has no automated accessibility violations in the decided export state", async () => {
    const decision = {
      action: "approve_treatment" as const,
      label: "Treatment approved for workpaper",
      rationale: "The exact allocation agrees with the cited evidence and policy.",
      actor_id: "demo-controller",
      finding_id: "finding-1",
      snapshot_sha256: "c".repeat(64),
      review_context_sha256: "e".repeat(64),
      event_sequence: 1,
      event_sha256: "d".repeat(64),
      created_at: "2026-07-14T07:56:50+00:00",
      event_chain_valid: true,
      stale: false,
      accounting_action_performed: false as const,
      erp_write_performed: false as const,
    };
    vi.stubGlobal("fetch", apiMock({ ...caseData, decision }));
    render(<App />);
    await screen.findByRole("button", { name: "Download validated workpaper" });

    const results = await axe(document.body);

    expect(results.violations).toEqual([]);
  });

  it("has no automated accessibility violations in the recoverable error state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Loopback unavailable")));
    render(<App />);
    await screen.findByRole("button", { name: "Retry case load" });

    const results = await axe(document.body);

    expect(results.violations).toEqual([]);
  });
});
