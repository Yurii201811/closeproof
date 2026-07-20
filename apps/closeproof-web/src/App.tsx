import { FormEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowDown,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  CornerDownRight,
  FileCheck2,
  FileText,
  HelpCircle,
  History,
  Inbox,
  ListChecks,
  LoaderCircle,
  Search,
  Settings,
  ShieldCheck,
  Workflow,
  X,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Advisory, AdvisoryProvider, AdvisoryStatus, Calculation, CloseProofCase, Decision, DecisionAction, Stage, StageStatus } from "./types";

const API_CASE = "/api/case";
const SAFETY_BOUNDARY = "Synthetic demo · Local controls · No ERP writes · Advisory optional";
const MOBILE_LAYOUT_QUERY = "(max-width: 1279px)";

export default function App() {
  const [caseData, setCaseData] = useState<CloseProofCase | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [sessionToken, setSessionToken] = useState("");
  const [selectedStage, setSelectedStage] = useState("adjustments");
  const [mobileProofOpen, setMobileProofOpen] = useState(
    () => new URLSearchParams(window.location.search).get("proof") === "open",
  );
  const [isMobileLayout, setIsMobileLayout] = useState(
    () => window.matchMedia?.(MOBILE_LAYOUT_QUERY).matches ?? false,
  );
  const initialLoadStarted = useRef(false);
  const selectedStageButton = useRef<HTMLButtonElement | null>(null);
  const hasReviewableStage = caseData?.stages.some((stage) => stage.id === "adjustments") ?? false;
  const proofModalOpen = hasReviewableStage && isMobileLayout && mobileProofOpen;

  const loadCase = async () => {
    setLoadState("loading");
    setLoadError("");
    try {
      const [caseResponse, sessionResponse] = await Promise.all([
        fetch(API_CASE, { headers: { Accept: "application/json" } }),
        fetch("/api/session", { headers: { Accept: "application/json" } }),
      ]);
      if (!caseResponse.ok) throw new Error(`Reviewer returned ${caseResponse.status}`);
      if (!sessionResponse.ok) throw new Error(`Reviewer session returned ${sessionResponse.status}`);
      const payload = (await caseResponse.json()) as CloseProofCase;
      const session = (await sessionResponse.json()) as { csrf_token?: unknown };
      if (payload.schema_version !== "closeproof-case-v1") throw new Error("Unsupported case schema");
      if (typeof session.csrf_token !== "string" || !session.csrf_token) throw new Error("Reviewer session did not provide CSRF protection");
      setCaseData(payload);
      setSessionToken(session.csrf_token);
      setSelectedStage(payload.selected_stage);
      setLoadState("ready");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "The case could not be loaded");
      setLoadState("error");
    }
  };

  useEffect(() => {
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    void loadCase();
  }, []);

  useEffect(() => {
    const matcher = window.matchMedia?.(MOBILE_LAYOUT_QUERY);
    if (!matcher) return;
    const updateLayout = () => {
      setIsMobileLayout(matcher.matches);
      if (!matcher.matches) setMobileProofOpen(false);
    };
    updateLayout();
    matcher.addEventListener("change", updateLayout);
    return () => matcher.removeEventListener("change", updateLayout);
  }, []);

  useEffect(() => {
    const closeWithEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && proofModalOpen) closeMobileProof();
    };
    window.addEventListener("keydown", closeWithEscape);
    return () => window.removeEventListener("keydown", closeWithEscape);
  }, [proofModalOpen]);

  useEffect(() => {
    if (!proofModalOpen) return;
    const htmlOverflow = document.documentElement.style.overflow;
    const bodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    return () => {
      document.documentElement.style.overflow = htmlOverflow;
      document.body.style.overflow = bodyOverflow;
    };
  }, [proofModalOpen]);

  const openStage = (stage: Stage, button: HTMLButtonElement) => {
    setSelectedStage(stage.id);
    selectedStageButton.current = button;
    if (stage.id === "adjustments" && isMobileLayout) setMobileProofOpen(true);
  };

  const closeMobileProof = () => {
    setMobileProofOpen(false);
    window.setTimeout(() => selectedStageButton.current?.focus(), 0);
  };

  if (loadState === "loading") return <LoadingScreen />;
  if (loadState === "error" || !caseData) {
    return <ErrorScreen message={loadError} onRetry={() => void loadCase()} />;
  }

  return (
    <div className="app-frame">
      <a className="skip-link" href="#close-ledger" inert={proofModalOpen}>Skip to close ledger</a>
      <SafetyStrip />
      <MobileHeader caseData={caseData} />
      <div className="workspace-shell">
        <ContextRail caseData={caseData} />
        <main className="close-workspace" id="close-ledger" tabIndex={-1} inert={proofModalOpen}>
          <CloseHeader caseData={caseData} />
          {caseData.stages.length ? (
            <StageLedger
              stages={caseData.stages}
              decision={activeDecision(caseData)}
              selectedStage={selectedStage}
              onSelect={openStage}
            />
          ) : (
            <EmptyState />
          )}
        </main>
        {hasReviewableStage && (
          <ProofDrawer
            caseData={caseData}
            mobileOpen={proofModalOpen}
            sessionToken={sessionToken}
            onClose={closeMobileProof}
            onCase={setCaseData}
          />
        )}
      </div>
    </div>
  );
}

function SafetyStrip() {
  return (
    <header className="safety-strip" aria-label="Product safety boundary">
      <span className="safety-dot" aria-hidden="true" />
      {SAFETY_BOUNDARY}
    </header>
  );
}

function Brand() {
  return (
    <div className="brand" aria-label="BalanceDocket">
      <FileCheck2 className="brand-mark" aria-hidden="true" strokeWidth={1.7} />
      <span>BalanceDocket</span>
    </div>
  );
}

function ContextRail({ caseData }: { caseData: CloseProofCase }) {
  const nav = [
    ["Close workflow", "flow"],
    ["Review queue", "queue"],
    ["Evidence library", "evidence"],
    ["Audit log", "audit"],
    ["Settings", "settings"],
  ];
  return (
    <aside className="context-rail" aria-label="BalanceDocket navigation">
      <Brand />
      <section className="context-block" aria-labelledby="current-context">
        <p className="eyebrow" id="current-context">Current context</p>
        <p className="context-label">Entity</p>
        <strong>{caseData.entity.name}</strong>
        <p className="context-label">Period</p>
        <strong>{caseData.period.label}</strong>
      </section>
      <nav aria-label="Primary">
        <p className="eyebrow">Navigation</p>
        <ul className="nav-list">
          {nav.map(([label, icon], index) => (
            <li key={label}>
              {index === 0 ? (
                <a className="nav-item active" href="#close-ledger" aria-current="page">
                  <NavIcon name={icon} />
                  {label}
                </a>
              ) : (
                <button className="nav-item" type="button" disabled title="Outside this focused competition demo">
                  <NavIcon name={icon} />
                  {label}<span className="sr-only"> — outside this focused demo</span>
                </button>
              )}
            </li>
          ))}
        </ul>
      </nav>
      <div className="rail-boundary">
        <ShieldCheck className="boundary-mark" aria-hidden="true" strokeWidth={1.7} />
        <span><strong>Review only</strong><small>No accounting action performed</small></span>
      </div>
    </aside>
  );
}

function MobileHeader({ caseData }: { caseData: CloseProofCase }) {
  return (
    <div className="mobile-header" role="region" aria-label="Mobile close context">
      <Brand />
      <div className="mobile-context">
        <strong>{caseData.entity.name}</strong>
        <span>{caseData.period.label}</span>
      </div>
    </div>
  );
}

function CloseHeader({ caseData }: { caseData: CloseProofCase }) {
  const decision = activeDecision(caseData);
  const decisionState = decision?.action === "approve_treatment"
    ? { title: "Decision recorded", className: "decision-complete" }
    : decision?.action === "request_evidence"
      ? { title: "Evidence requested", className: "decision-attention" }
      : decision?.action === "reject"
        ? { title: "Treatment rejected", className: "decision-rejected" }
        : null;
  const exceptionCount = caseData.stages.filter(
    (stage) => stage.status === "review_required" || stage.status === "blocked",
  ).length;
  const exceptionLabel = exceptionCount === 1 ? "exception requires review" : "exceptions require review";
  const title = decisionState ? replaceCloseState(caseData.title, decisionState.title) : caseData.title;
  return (
    <header className="close-header">
      <div>
        <p className="eyebrow">Period close · Controller review</p>
        <h1>{title}</h1>
        <p>{caseData.subtitle}</p>
      </div>
      <div className={decisionState ? `header-status ${decisionState.className}` : "header-status"} aria-label={decisionState ? "1 human decision recorded" : `${exceptionCount} ${exceptionLabel}`}>
        <strong>{decisionState ? 1 : exceptionCount}</strong>
        <span>{decisionState ? "human decision" : exceptionCount === 1 ? "exception" : "exceptions"}<br />{decisionState ? "recorded" : exceptionCount === 1 ? "requires review" : "require review"}</span>
      </div>
    </header>
  );
}

function StageLedger({ stages, decision, selectedStage, onSelect }: { stages: Stage[]; decision: Decision | null; selectedStage: string; onSelect: (stage: Stage, button: HTMLButtonElement) => void }) {
  return (
    <section className="ledger" aria-labelledby="ledger-title">
      <div className="ledger-columns" aria-hidden="true">
        <span>Status / stage</span><span>Owner</span><span>Evidence</span><span>Blocker</span><span>Next action</span>
      </div>
      <h2 className="sr-only" id="ledger-title">Nine-stage close dependency ledger</h2>
      <ol className="stage-list">
        {stages.map((stage) => {
          const presentedStage = presentStage(stage, decision);
          const rowContent = (
            <>
              <span className="stage-primary">
                <span className="stage-number" aria-hidden="true">{presentedStage.number}</span>
                <StatusMark status={presentedStage.status} label={presentedStage.status_label} />
                <span className="stage-title"><strong>{presentedStage.title}</strong>{presentedStage.id === "adjustments" && presentedStage.blocker && <small>{presentedStage.blocker}</small>}</span>
              </span>
              <span className="stage-meta owner"><span className="mobile-label">Owner</span>{presentedStage.owner}</span>
              <span className="stage-meta evidence"><span className="mobile-label">Evidence</span>{presentedStage.evidence_count} {presentedStage.evidence_count === 1 ? "item" : "items"}</span>
              <span className="stage-meta blocker"><span className="mobile-label">Blocker</span>{presentedStage.blocker ?? "—"}</span>
              <span className="stage-meta next"><span className="mobile-label">Next</span>{presentedStage.next_action}</span>
            </>
          );
          const isReviewable = presentedStage.id === "adjustments";
          return (
            <li className={`stage-node ${presentedStage.status}`} key={presentedStage.id}>
              <span className="spine-point" aria-hidden="true" />
              {isReviewable ? (
                <button
                  className={presentedStage.id === selectedStage ? "stage-row selected" : "stage-row"}
                  type="button"
                  aria-current={presentedStage.id === selectedStage ? "step" : undefined}
                  aria-label={`${presentedStage.number}. ${presentedStage.title}. ${presentedStage.status_label}. ${presentedStage.blocker ?? presentedStage.next_action}`}
                  onClick={(event) => onSelect(stage, event.currentTarget)}
                >
                  {rowContent}
                  <ChevronRight className="row-arrow" aria-hidden="true" />
                </button>
              ) : (
                <div className="stage-row readonly">{rowContent}</div>
              )}
            </li>
          );
        })}
      </ol>
      <p className="ledger-note"><CornerDownRight aria-hidden="true" /> {ledgerNote(decision)}</p>
    </section>
  );
}

function StatusMark({ status, label }: { status: StageStatus; label: string }) {
  const icons: Record<StageStatus, LucideIcon> = {
    complete: CheckCircle2,
    waiting: Clock3,
    blocked: XCircle,
    review_required: AlertCircle,
  };
  const StatusIcon = icons[status];
  return (
    <span className={`status-mark ${status}`}>
      <StatusIcon className="status-icon" aria-hidden="true" strokeWidth={1.8} />
      <span>{label}</span>
    </span>
  );
}

function ProofDrawer({ caseData, mobileOpen, sessionToken, onClose, onCase }: { caseData: CloseProofCase; mobileOpen: boolean; sessionToken: string; onClose: () => void; onCase: (caseData: CloseProofCase) => void }) {
  const [rationale, setRationale] = useState(caseData.decision?.stale ? "" : caseData.decision?.rationale ?? "");
  const [submitState, setSubmitState] = useState<"idle" | "saving" | "error">("idle");
  const [exportState, setExportState] = useState<"idle" | "loading" | "complete" | "error">("idle");
  const [message, setMessage] = useState("");
  const closeButton = useRef<HTMLButtonElement | null>(null);
  const rationaleInput = useRef<HTMLTextAreaElement | null>(null);
  const exportButton = useRef<HTMLButtonElement | null>(null);
  const focusDecisionResult = useRef(false);
  const focusAdvisoryResult = useRef(false);
  const reviewContext = useRef(caseData.review_context_sha256);
  const finding = caseData.finding;
  const calculation = finding.calculation;
  const decisionIntegrityFailed = Boolean(caseData.decision && !caseData.decision.event_chain_valid);
  const currentDecision = caseData.decision && !caseData.decision.stale && caseData.decision.event_chain_valid ? caseData.decision : null;
  const decisionLocked = Boolean(currentDecision || decisionIntegrityFailed);
  const displayedRationale = currentDecision?.rationale ?? rationale;
  const rationaleCharacters = displayedRationale.trim().length;
  const rationaleValid = rationaleCharacters >= 12 && rationaleCharacters <= 1000;

  useEffect(() => {
    if (!mobileOpen) return;
    // Move focus after the activating click, then retry once after the drawer's
    // visibility transition settles. Firefox/WebKit can reject focus while an
    // off-canvas element is still becoming visible under reduced motion.
    let focusEstablished = false;
    const moveFocus = () => {
      closeButton.current?.focus();
      focusEstablished = document.activeElement === closeButton.current;
    };
    const focusTimer = window.setTimeout(moveFocus, 0);
    const settledFocusTimer = window.setTimeout(() => {
      if (!focusEstablished) moveFocus();
    }, 50);
    return () => {
      window.clearTimeout(focusTimer);
      window.clearTimeout(settledFocusTimer);
    };
  }, [mobileOpen]);

  useEffect(() => {
    if (reviewContext.current === caseData.review_context_sha256) return;
    reviewContext.current = caseData.review_context_sha256;
    setRationale("");
    setSubmitState("idle");
    setExportState("idle");
    setMessage("Review context changed. Review the updated advisory and enter a fresh rationale.");
    if (focusAdvisoryResult.current) {
      focusAdvisoryResult.current = false;
      rationaleInput.current?.focus();
    }
  }, [caseData.review_context_sha256]);

  useEffect(() => {
    if (!currentDecision || !focusDecisionResult.current) return;
    focusDecisionResult.current = false;
    exportButton.current?.focus();
  }, [currentDecision?.event_sha256]);

  const trapModalFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!mobileOpen || event.key !== "Tab") return;
    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const recordDecision = async (action: DecisionAction) => {
    if (!rationaleValid) {
      setMessage("Add a rationale of at least 12 characters before deciding.");
      return;
    }
    setSubmitState("saving");
    setMessage("Recording the evidence-bound human decision…");
    try {
      const response = await fetch("/api/decisions", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CloseProof-CSRF": sessionToken },
        body: JSON.stringify({
          action,
          rationale: rationale.trim(),
          snapshot_sha256: caseData.snapshot_sha256,
          review_context_sha256: caseData.review_context_sha256,
          finding_id: caseData.finding_id,
          actor_id: "demo-controller",
        }),
      });
      const payload = (await response.json()) as { case?: CloseProofCase; decision?: Decision; error?: string };
      if (!response.ok) throw new Error(payload.error ?? `Decision returned ${response.status}`);
      if (!payload.case || payload.case.schema_version !== "closeproof-case-v1") {
        throw new Error("The reviewer did not return the authoritative review case");
      }
      focusDecisionResult.current = true;
      onCase(payload.case);
      setSubmitState("idle");
      setMessage(`${payload.decision?.label ?? "Human decision recorded"}. No posting or ERP action occurred.`);
    } catch (error) {
      setSubmitState("error");
      setMessage(error instanceof Error ? error.message : "The decision could not be recorded");
    }
  };

  const handleSubmit = (event: FormEvent) => event.preventDefault();

  const handleAdvisoryCase = (updatedCase: CloseProofCase) => {
    focusAdvisoryResult.current = true;
    onCase(updatedCase);
  };

  const focusRationale = () => {
    rationaleInput.current?.focus();
    if (typeof rationaleInput.current?.scrollIntoView === "function") {
      rationaleInput.current.scrollIntoView({ block: "center" });
    }
  };

  const exportWorkpaper = async () => {
    if (!currentDecision) return;
    setExportState("loading");
    setMessage("Validating the workpaper before download…");
    try {
      const response = await fetch("/api/workpaper", { headers: { Accept: "application/json" } });
      const payload = (await response.json()) as Record<string, unknown>;
      if (!response.ok) throw new Error(typeof payload.error === "string" ? payload.error : `Workpaper returned ${response.status}`);
      const exportedDecision = payload.human_decision as Record<string, unknown> | undefined;
      const eventChain = payload.event_chain as Record<string, unknown> | undefined;
      const externalActions = payload.external_actions_performed;
      if (
        payload.schema_version !== "closeproof-workpaper-v1"
        || payload.snapshot_sha256 !== caseData.snapshot_sha256
        || payload.review_context_sha256 !== caseData.review_context_sha256
        || exportedDecision?.event_sha256 !== currentDecision.event_sha256
        || eventChain?.valid !== true
        || eventChain?.semantic_validation_scope !== "current_decision"
        || eventChain?.semantically_validated_event_sha256 !== currentDecision.event_sha256
        || eventChain?.semantically_validated_event_sequence !== currentDecision.event_sequence
        || !Array.isArray(externalActions)
        || externalActions.length !== 0
      ) {
        throw new Error("The downloaded workpaper failed BalanceDocket integrity checks");
      }
      const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `balancedocket-${caseData.case_id}-workpaper.json`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setExportState("complete");
      setMessage("Validated workpaper downloaded. No accounting or ERP action occurred.");
    } catch (error) {
      setExportState("error");
      setMessage(error instanceof Error ? error.message : "The workpaper could not be downloaded");
    }
  };

  return (
    <aside className={mobileOpen ? "proof-drawer mobile-open" : "proof-drawer"} aria-labelledby="proof-title" aria-modal={mobileOpen || undefined} role={mobileOpen ? "dialog" : "complementary"} onKeyDown={trapModalFocus}>
      <header className="proof-header">
        <div>
          <p className="eyebrow">Selected proof · Adjustments</p>
          <h2 id="proof-title">{finding.title} <span>· {finding.amount_label}</span></h2>
        </div>
        <button ref={closeButton} className="icon-button close-proof" type="button" onClick={onClose} aria-label="Close proof sheet"><X aria-hidden="true" /></button>
      </header>

      <div className="proof-scroll">
        <ProofSection number="1" title="Source evidence" aside={`${finding.source.document_id} · page ${finding.source.page} · ${finding.source.line_range}`}>
          <div className="document-meta">
            <DocumentIcon />
            <span><strong>Invoice {finding.source.document_id} · {finding.source.supplier}</strong><small>Dated {formatDate(finding.source.invoice_date)} · synthetic fixture</small></span>
          </div>
          <blockquote className="evidence-quote">
            <span aria-hidden="true">“</span>
            <mark>{finding.source.citation.text}</mark>
          </blockquote>
          <p className="source-id">{finding.source.citation.source_id} · SHA {shortHash(finding.source.citation.evidence_sha256)}</p>
        </ProofSection>

        <ProofSection number="2" title="Deterministic allocation" aside={calculation.label}>
          <ControlResults checks={caseData.checks} />
          <dl className="calculation-summary">
            <div><dt>Total invoice</dt><dd>{finding.amount_label}</dd></div>
            <div><dt>Service period</dt><dd>{formatDate(calculation.service_start)} → {formatDate(calculation.service_end)} <small>({calculation.service_days} days)</small></dd></div>
            <div><dt>Current period</dt><dd>{formatDate(currentPeriodStart(calculation))} → {formatDate(calculation.period_end)} <small>({calculation.current_period_days} days)</small></dd></div>
          </dl>
          <div className="allocation-table" role="table" aria-label="Deterministic allocation">
            <div className="allocation-head" role="row"><span role="columnheader">Component</span><span role="columnheader">Formula</span><span role="columnheader">Amount</span></div>
            <div role="row"><span role="cell">Current-period expense</span><code role="cell">{displayFormula(calculation)}</code><strong role="cell">{calculation.current_period_expense_label}</strong></div>
            <div role="row"><span role="cell">Prepaid asset</span><code role="cell">{amountWithoutCurrency(finding.amount_label)} − {amountWithoutCurrency(calculation.current_period_expense_label)}</code><strong role="cell">{calculation.prepaid_asset_label}</strong></div>
          </div>
          <p className="control-stamp"><Check aria-hidden="true" /> Exact integer-öre result · no model arithmetic</p>
        </ProofSection>

        <AdvisoryPanel advisory={caseData.advisory} sessionToken={sessionToken} onCase={handleAdvisoryCase} />

        <form className="decision-form" onSubmit={handleSubmit}>
          <label htmlFor="rationale"><span>4. Human rationale</span><small>{currentDecision ? "Recorded rationale" : rationaleCharacters < 12 ? `${rationaleCharacters}/12 minimum` : `${displayedRationale.length}/1000`}</small></label>
          <textarea ref={rationaleInput} id="rationale" value={displayedRationale} maxLength={1000} readOnly={decisionLocked} onChange={(event) => { if (!decisionLocked) { setRationale(event.target.value); setMessage(""); } }} placeholder="Record why the cited evidence and exact allocation support your decision…" aria-describedby="rationale-help" aria-invalid={!decisionLocked && displayedRationale.length > 0 && !rationaleValid ? true : undefined} />
          <p id="rationale-help">{currentDecision ? "This recorded rationale is read-only. " : rationaleCharacters < 12 ? `${12 - rationaleCharacters} more characters required. ` : "Rationale ready. "}{!currentDecision && "Use synthetic reasoning only; do not include personal data or secrets. "}Stored against snapshot {shortHash(caseData.snapshot_sha256)}.</p>
        </form>

        {currentDecision && (
          <div className={`decision-record ${currentDecision.action}`}>
            <CheckCircle2 className="decision-icon" aria-hidden="true" />
            <div><strong>{currentDecision.label}</strong><p>Event {currentDecision.event_sequence} · local hash chain consistent · no ERP write</p></div>
          </div>
        )}
        {caseData.decision?.stale && (
          <div className="decision-record stale" role="alert">
            <AlertCircle className="decision-icon" aria-hidden="true" />
            <div><strong>Previous decision is stale</strong><p>The advisory context changed. Record a new human decision before export.</p></div>
          </div>
        )}
        {decisionIntegrityFailed && (
          <div className="decision-record stale" role="alert">
            <XCircle className="decision-icon" aria-hidden="true" />
            <div><strong>Decision chain integrity failed</strong><p>Export and further decisions are blocked. Regenerate the synthetic demo.</p></div>
          </div>
        )}
      </div>

      <div className="proof-footer">
        <div className="provenance-row">
          <span>Snapshot SHA <code>{shortHash(caseData.snapshot_sha256)}</code></span>
          <span><i className={currentDecision ? "human-state decided" : "human-state"} aria-hidden="true" /> {decisionIntegrityFailed ? "Decision integrity failed" : currentDecision ? "Human decision recorded" : "Human decision pending"}</span>
        </div>
        {currentDecision ? (
          <div className="export-bar">
            <button ref={exportButton} className="export-button" type="button" disabled={exportState === "loading"} onClick={() => void exportWorkpaper()}>{exportState === "loading" ? "Validating workpaper…" : exportState === "complete" ? "Download again" : "Download validated workpaper"}</button>
          </div>
        ) : decisionIntegrityFailed ? null : rationaleValid ? (
          <div className="action-bar" aria-label="Reviewer actions">
            <button className="approve-button" type="button" disabled={submitState === "saving" || decisionLocked} onClick={() => void recordDecision("approve_treatment")}><Check aria-hidden="true" /> Approve treatment</button>
            <button className="evidence-button" type="button" disabled={submitState === "saving" || decisionLocked} onClick={() => void recordDecision("request_evidence")}><HelpCircle aria-hidden="true" /> Request evidence</button>
            <button className="reject-button" type="button" disabled={submitState === "saving" || decisionLocked} onClick={() => void recordDecision("reject")}><X aria-hidden="true" /> Reject</button>
          </div>
        ) : (
          <div className="continue-bar">
            <button className="continue-button" type="button" onClick={focusRationale}>Continue to human rationale <ArrowDown aria-hidden="true" /></button>
          </div>
        )}
        <div className="footer-status" role="status" aria-live="polite">
          {message || (decisionIntegrityFailed ? "Decision chain integrity failed. Regenerate the demo." : currentDecision ? "Decision locked to this evidence snapshot; export is read-only." : rationaleValid ? "Rationale ready. Choose one human action." : caseData.decision?.stale ? "Review context changed; a fresh rationale is required." : "Continue to the rationale to unlock human actions.")}
        </div>
      </div>
    </aside>
  );
}

const advisoryState: Record<AdvisoryStatus, { label: string; summary: string }> = {
  not_requested: { label: "Not requested", summary: "Local controls are complete. A model advisory is optional and no provider was contacted." },
  running: { label: "Running", summary: "An advisory was requested and is awaiting a validated result." },
  completed: { label: "Completed", summary: "A structured advisory is available. Human review remains required." },
  unavailable: { label: "Unavailable", summary: "The advisory could not be obtained. Local controls and human review remain available." },
  invalid: { label: "Invalid", summary: "The advisory failed validation and is excluded from the review conclusion." },
};

function AdvisoryStateIcon({ status }: { status: AdvisoryStatus }) {
  const icons: Record<AdvisoryStatus, LucideIcon> = {
    not_requested: Circle,
    running: LoaderCircle,
    completed: CheckCircle2,
    unavailable: AlertCircle,
    invalid: XCircle,
  };
  const StateIcon = icons[status];
  return <StateIcon className="advisory-state-icon" aria-hidden="true" strokeWidth={1.8} />;
}

const providerNames: Record<AdvisoryProvider, string> = {
  none: "No provider",
  codex_session: "Codex session",
  codex_cli: "Codex CLI",
  chatgpt_manual: "ChatGPT manual import",
  openai_api: "OpenAI API",
};

function providerAssurance(advisory: Advisory) {
  if (advisory.provider === "chatgpt_manual") return "Manual import · Unverified model identity";
  if (advisory.provider === "codex_session" || advisory.provider === "codex_cli") {
    return advisory.status === "running"
      ? "Codex requested · Validation pending"
      : advisory.status === "completed" && advisory.provenance.schema_validated
        ? "Codex requested · Validated output"
        : "Codex route · No validated output";
  }
  if (advisory.provider === "openai_api") {
    if (advisory.status === "running") return "API route · Validation pending";
    return advisory.status === "completed" && advisory.provenance.schema_validated
      ? "API response · Verified"
      : "API route · No validated response";
  }
  return "No provider · Advisory optional";
}

function manualImportErrorMessage(code: string) {
  const messages: Record<string, string> = {
    invalid_import: "The pasted advisory did not match the required import fields. Check the JSON and try again.",
    invalid_advisory_json: "The pasted response was not a valid advisory JSON object.",
    invalid_citations: "The advisory cited evidence outside this review snapshot.",
    deterministic_amount_changed: "The advisory changed a controlled amount and was rejected.",
    approval_authority_claimed: "The advisory claimed decision authority and was rejected.",
    model_mismatch: "The optional reported model did not match GPT-5.6. Leave the field blank unless ChatGPT explicitly reports its model.",
  };
  return messages[code] ?? `The advisory was rejected safely (${code}). Check the structured response and try again.`;
}

const CLIPBOARD_WRITE_TIMEOUT_MS = 1_000;

async function writeClipboardWithTimeout(text: string) {
  if (!navigator.clipboard?.writeText) {
    throw new Error("clipboard_unavailable");
  }
  let timeoutId: number | undefined;
  try {
    await Promise.race([
      navigator.clipboard.writeText(text),
      new Promise<never>((_resolve, reject) => {
        timeoutId = window.setTimeout(
          () => reject(new Error("clipboard_timeout")),
          CLIPBOARD_WRITE_TIMEOUT_MS,
        );
      }),
    ]);
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
}

function AdvisoryPanel({ advisory, sessionToken, onCase }: { advisory: Advisory; sessionToken: string; onCase: (caseData: CloseProofCase) => void }) {
  const [promptState, setPromptState] = useState<"idle" | "loading" | "copied" | "manual" | "error">("idle");
  const [preparedPrompt, setPreparedPrompt] = useState("");
  const [importState, setImportState] = useState<"idle" | "saving" | "error" | "complete">("idle");
  const [manualPayload, setManualPayload] = useState("");
  const [reportedModel, setReportedModel] = useState("");
  const [manualMessage, setManualMessage] = useState("");
  const state = advisoryState[advisory.status];
  const stateSummary = advisory.status === "running" && advisory.provider === "chatgpt_manual"
    ? "Prompt prepared locally; no provider was contacted. Awaiting a manually supplied result."
    : state.summary;
  const output = advisory.status === "completed" ? advisory.output : null;
  const showManualFallback = advisory.status === "not_requested"
    || advisory.status === "unavailable"
    || advisory.status === "invalid"
    || (advisory.status === "running" && advisory.provider === "chatgpt_manual");

  const copyPrompt = async () => {
    setPromptState("loading");
    setManualMessage("Preparing the evidence-bound prompt…");
    try {
      const response = await fetch("/api/advisory/prompt", { headers: { Accept: "application/json" } });
      const payload = (await response.json()) as { prompt?: unknown; error?: string };
      if (!response.ok) throw new Error(payload.error ?? `Prompt returned ${response.status}`);
      if (typeof payload.prompt !== "string" || !payload.prompt) throw new Error("The reviewer returned an empty prompt");
      setPreparedPrompt(payload.prompt);
      try {
        await writeClipboardWithTimeout(payload.prompt);
        setPromptState("copied");
        setManualMessage("Prompt copied. No provider was contacted by BalanceDocket.");
      } catch {
        setPromptState("manual");
        setManualMessage("Automatic clipboard access was unavailable. Select the prepared prompt below and copy it manually.");
      }
    } catch (error) {
      setPromptState("error");
      setManualMessage(error instanceof Error ? error.message : "The prompt could not be copied");
    }
  };

  const importManualAdvisory = async (event: FormEvent) => {
    event.preventDefault();
    let payload: unknown;
    try {
      payload = JSON.parse(manualPayload);
    } catch {
      setImportState("error");
      setManualMessage("Paste a valid JSON advisory before importing.");
      return;
    }
    setImportState("saving");
    setManualMessage("Validating the pasted advisory against the review context…");
    try {
      const response = await fetch("/api/advisory/import", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CloseProof-CSRF": sessionToken },
        body: JSON.stringify({ payload, ...(reportedModel.trim() ? { reported_model: reportedModel.trim() } : {}) }),
      });
      const result = (await response.json()) as { case?: CloseProofCase; error?: string };
      if (!response.ok) throw new Error(result.error ? manualImportErrorMessage(result.error) : `Import returned ${response.status}`);
      if (!result.case || result.case.schema_version !== "closeproof-case-v1") {
        throw new Error("The reviewer did not return the updated review context");
      }
      onCase(result.case);
      setImportState("complete");
      setManualMessage("Manual advisory imported. Model identity remains unverified.");
    } catch (error) {
      setImportState("error");
      setManualMessage(error instanceof Error ? error.message : "The advisory could not be imported");
    }
  };

  return (
    <ProofSection number="3" title="Model advisory" aside="Advisory — cannot approve" tone={`advisory advisory-${advisory.status}`}>
      <div className="advisory-status" role="status" aria-live="polite" aria-atomic="true">
        <AdvisoryStateIcon status={advisory.status} />
          <span><strong>{state.label}</strong><small>{stateSummary}</small></span>
      </div>
      <div className="advisory-provider" aria-label={`Provider: ${providerNames[advisory.provider]}. Assurance: ${providerAssurance(advisory)}`}>
        <span><small>Provider</small><strong>{providerNames[advisory.provider]}</strong></span>
        <span><small>Assurance</small><strong>{providerAssurance(advisory)}</strong></span>
      </div>

      {output && (
        <div className="advisory-output">
          <div className="advisory-meta"><span>Uncertainty: {output.uncertainty}</span><span>Cannot approve: yes</span></div>
          <p className="controlled-display-note"><ShieldCheck aria-hidden="true" /> Controlled display generated locally; provider prose is not stored.</p>
          <p className="advisory-conclusion">{output.conclusion}</p>
          <p>{output.rationale}</p>
          <div className="citation-chips" aria-label="Advisory citations">
            {output.citation_ids.map((citation) => <code key={citation}>{citation}</code>)}
          </div>
          {output.missing_evidence.length > 0 && <p className="missing-evidence"><strong>Still requires:</strong> {output.missing_evidence.join("; ")}</p>}
        </div>
      )}

      {advisory.status === "completed" && !output && <p className="advisory-warning"><strong>No validated output.</strong> Treat this advisory as unavailable.</p>}
      {advisory.safe_error_code && <p className="advisory-error"><strong>Safe error:</strong> <code>{advisory.safe_error_code}</code></p>}

      {advisory.provider !== "none" && (
        <details className="provenance-disclosure">
          <summary>Provider provenance</summary>
          <dl>
            <div><dt>Transport</dt><dd>{advisory.provenance.transport ?? "Not reported"}</dd></div>
            <div><dt>Schema</dt><dd>{advisory.provenance.schema_validated ? "Validated" : "Not validated"}</dd></div>
            <div><dt>Requested model</dt><dd>{advisory.provenance.requested_model ?? "Not reported"}</dd></div>
            <div><dt>Reported model</dt><dd>{advisory.provenance.reported_model ?? "Not reported"}</dd></div>
            <div><dt>Attestation</dt><dd>{advisory.provenance.model_attestation ?? "None"}</dd></div>
            {advisory.provenance.run_id && <div><dt>Run ID</dt><dd><code>{advisory.provenance.run_id}</code></dd></div>}
            {advisory.provenance.response_id && <div><dt>Response ID</dt><dd><code>{advisory.provenance.response_id}</code></dd></div>}
            {advisory.provenance.payload_sha256 && <div><dt>Provider payload SHA</dt><dd><code>{shortHash(advisory.provenance.payload_sha256)}</code></dd></div>}
            {advisory.provenance.controlled_display_sha256 && <div><dt>Controlled display SHA</dt><dd><code>{shortHash(advisory.provenance.controlled_display_sha256)}</code></dd></div>}
            {advisory.provenance.evidence_snapshot_sha256 && <div><dt>Evidence SHA</dt><dd><code>{shortHash(advisory.provenance.evidence_snapshot_sha256)}</code></dd></div>}
          </dl>
        </details>
      )}

      {showManualFallback && (
        <div className="manual-fallback">
          <div className="manual-actions" aria-label="Optional manual advisory workflow">
            <button type="button" onClick={() => void copyPrompt()} disabled={promptState === "loading"}>{promptState === "loading" ? "Preparing…" : promptState === "copied" ? "Prompt copied" : promptState === "manual" ? "Retry copy" : "Copy prompt"}</button>
            <a href="https://chatgpt.com/" target="_blank" rel="noreferrer">Open ChatGPT <ArrowUpRight aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a>
          </div>
          {preparedPrompt && (
            <div className="prepared-prompt">
              <label htmlFor="prepared-advisory-prompt">Evidence-bound prompt</label>
              <p id="prepared-advisory-prompt-help">If automatic copying is blocked, focus this field, select all, and copy it manually.</p>
              <textarea
                id="prepared-advisory-prompt"
                value={preparedPrompt}
                readOnly
                aria-describedby="prepared-advisory-prompt-help"
                onFocus={(event) => event.currentTarget.select()}
              />
            </div>
          )}
          <details className="manual-import">
            <summary>Paste manual result</summary>
            <form onSubmit={(event) => void importManualAdvisory(event)}>
              <label htmlFor="manual-advisory">Advisory JSON</label>
              <textarea id="manual-advisory" value={manualPayload} onChange={(event) => setManualPayload(event.target.value)} placeholder="Paste the structured JSON response" required />
              <label htmlFor="reported-model">Reported model <span>(optional, unverified; leave blank unless explicitly reported)</span></label>
              <input id="reported-model" value={reportedModel} onChange={(event) => setReportedModel(event.target.value)} autoComplete="off" />
              <button type="submit" disabled={!manualPayload.trim() || importState === "saving"}>{importState === "saving" ? "Validating…" : "Import advisory"}</button>
            </form>
          </details>
          <p className={`manual-message ${promptState === "error" || importState === "error" ? "error" : ""}`} role="status" aria-live="polite">{manualMessage || "Optional: use a server-built prompt and import the structured result. BalanceDocket does not verify manual model identity."}</p>
        </div>
      )}
    </ProofSection>
  );
}

function ProofSection({ number, title, aside, tone, children }: { number: string; title: string; aside: string; tone?: string; children: ReactNode }) {
  return (
    <section className={tone ? `proof-section ${tone}` : "proof-section"}>
      <header><h3><span>{number}.</span> {title}</h3><small>{aside}</small></header>
      {children}
    </section>
  );
}

function ControlResults({ checks }: { checks: CloseProofCase["checks"] }) {
  if (!checks.length) return null;
  return (
    <div className="control-results" role="list" aria-label="Deterministic control results">
      {checks.map((check) => {
        const verified = check.status === "verified";
        return (
          <div className={verified ? "control-result verified" : "control-result review-required"} role="listitem" key={check.id}>
            {verified
              ? <CheckCircle2 className="control-result-icon" aria-hidden="true" />
              : <AlertCircle className="control-result-icon" aria-hidden="true" />}
            <span><strong>{check.label}</strong><small>{check.result}</small></span>
            <em>{check.calculated_by}</em>
          </div>
        );
      })}
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="app-frame loading-screen" aria-busy="true">
      <SafetyStrip />
      <main className="state-page">
        <Brand />
        <p className="eyebrow">Binding the evidence snapshot</p>
        <h1>Preparing the close ledger</h1>
        <p>Verifying the synthetic invoice, ledger, policy, and deterministic controls.</p>
        <div className="skeleton-ledger" aria-hidden="true">{Array.from({ length: 6 }).map((_, index) => <i key={index} />)}</div>
      </main>
    </div>
  );
}

function ErrorScreen({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="app-frame error-screen">
      <SafetyStrip />
      <main className="state-page" aria-labelledby="closeproof-error-title">
        <Brand />
        <p className="eyebrow">Reviewer unavailable</p>
        <h1 id="closeproof-error-title">The evidence case could not be loaded</h1>
        <p role="alert">{message || "Start the loopback BalanceDocket server and try again."}</p>
        <button className="approve-button" type="button" onClick={onRetry}>Retry case load</button>
        <code>python3 -m accounting_agent.cli closeproof-serve</code>
      </main>
    </div>
  );
}

function EmptyState() {
  return (
    <section className="empty-state">
      <Inbox aria-hidden="true" />
      <h2>No close stages are available</h2>
      <p>Regenerate the synthetic case. No decision can be made without a complete stage ledger.</p>
    </section>
  );
}

function NavIcon({ name }: { name: string }) {
  const icons: Record<string, LucideIcon> = {
    flow: Workflow,
    queue: Search,
    evidence: ListChecks,
    audit: History,
    settings: Settings,
  };
  const Icon = icons[name] ?? FileText;
  return <Icon aria-hidden="true" />;
}

function DocumentIcon() {
  return <FileText className="document-icon" aria-hidden="true" />;
}

function shortHash(value: string) {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function activeDecision(caseData: CloseProofCase): Decision | null {
  return caseData.decision
    && !caseData.decision.stale
    && caseData.decision.event_chain_valid
    ? caseData.decision
    : null;
}

function replaceCloseState(title: string, state: string) {
  return title.includes("—")
    ? title.replace(/—.*$/, `— ${state}`)
    : `${title} — ${state}`;
}

function presentStage(stage: Stage, decision: Decision | null): Stage {
  if (!decision) return stage;
  if (stage.id === "adjustments") {
    if (decision.action === "approve_treatment") {
      return { ...stage, status: "complete", status_label: "Decision recorded", blocker: null, next_action: "Continue close outside this focused demo" };
    }
    if (decision.action === "request_evidence") {
      return { ...stage, status_label: "Evidence requested", blocker: "Additional evidence requested", next_action: "Collect supporting evidence" };
    }
    return { ...stage, status_label: "Treatment rejected", blocker: "Proposed treatment rejected", next_action: "Prepare a revised treatment" };
  }
  if (stage.status !== "waiting") return stage;
  if (decision.action === "approve_treatment") {
    return { ...stage, status_label: "Waiting on remaining controls", blocker: "Next controls not run", next_action: "Continue close outside this focused demo" };
  }
  if (decision.action === "request_evidence") {
    return { ...stage, status_label: "Waiting on evidence", blocker: "Additional evidence requested", next_action: "Await supporting evidence" };
  }
  return { ...stage, status_label: "Waiting on revised treatment", blocker: "Proposed treatment rejected", next_action: "Await revised treatment" };
}

function ledgerNote(decision: Decision | null) {
  if (!decision) return "Downstream stages remain waiting until the evidence-bound Adjustments decision is recorded.";
  if (decision.action === "approve_treatment") return "The Adjustments decision is recorded. Remaining close stages are outside this focused demo; no ERP action occurred.";
  if (decision.action === "request_evidence") return "The evidence request is recorded. Downstream stages remain waiting for the requested support; no ERP action occurred.";
  return "The rejection is recorded. Downstream stages remain waiting for a revised treatment; no ERP action occurred.";
}

function currentPeriodStart(calculation: Calculation) {
  return calculation.service_start > calculation.period_start
    ? calculation.service_start
    : calculation.period_start;
}

function displayFormula(calculation: Calculation) {
  const invoiceAmount = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(
    calculation.total_invoice_ore / 100,
  );
  return calculation.formula.replace(String(calculation.total_invoice_ore), invoiceAmount);
}

function amountWithoutCurrency(value: string) {
  return value.replace(/^[A-Z]{3}\s+/, "");
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
}
