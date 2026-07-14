# CloseProof problem validation

Status: qualitative validation on July 14, 2026. These signals support the
problem pattern and product boundary; they do **not** establish market size,
willingness to pay, or measured time savings.

## Practitioner signals

| Source | Public signal | CloseProof implication | Caveat |
|---|---|---|---|
| [Reddit: Need Month End Close Software Tool](https://www.reddit.com/r/Accounting/comments/1jqcym6/need_month_end_close_software_tool/) (April 3, 2025) | A finance team at a 400-person company attributed a 17-day close to manual spreadsheet work and transaction reconciliation. | Close latency and reconciliation toil remain concrete problems even with a substantial finance team. | Anonymous single-company account; some replies are vendor-promotional. |
| [Reddit: How do you stay organized during month-end close?](https://www.reddit.com/r/Accounting/comments/1ov4v7p/how_do_you_stay_organized_and_efficient_during/) (November 12, 2025) | A practitioner described Excel status tracking plus manual Teams follow-up for review readiness and delays. | Evidence, review handoff, and human accountability should live in one exception path. | One unverified practitioner comment. |
| [Reddit: automated bank reconciliation and AI](https://www.reddit.com/r/Accounting/comments/1ue5zr7/i_automated_a_bank_reconciliation_process_now_my/) (search-index date June 24, 2026) | The post described large reconciliation time savings from deterministic automation; replies questioned AI repeatability, hallucination, verification, controls, and audit trails. | Keep arithmetic deterministic and model interpretation advisory, cited, and reviewable. | Anonymous and recent; Reddit's rendered relative age was inconsistent, so the date is search-index metadata. |
| [Box on X: document extraction needs validation and human review](https://x.com/Box/status/2011865001867559421) (January 15, 2026) | The production pattern pairs extraction with permissions, validation rules, and human-review loops. | Treat evidence ingestion and review controls as product infrastructure, not prompt decoration. | Vendor marketing and not accounting-specific. |

## Corroborating professional sources

- [Deloitte, AI's real-world impact on controllership](https://www.deloitte.com/us/en/services/audit/blogs/accounting-finance/ai-real-world-impact-on-the-controllership-function.html)
  (April 20, 2025) describes fragmented sources, manual mappings,
  reconciliation, adjustments, and validation as close bottlenecks, while
  retaining human validation for final output.
- [Journal of Accountancy, How AI is transforming the audit](https://www.journalofaccountancy.com/issues/2026/feb/how-ai-is-transforming-the-audit-and-what-it-means-for-cpas/)
  (February 1, 2026) emphasizes verifiable citations, professional
  responsibility, skepticism, and human approval around AI-assisted
  reconciliation and draft adjustments.

These are professional-practice perspectives, not controlled market research.

## Verified product hypothesis

The strongest wedge is an **evidence-bound exception review layer**, not a full
close-management replacement and not an autonomous accountant:

1. trace each conclusion to source evidence;
2. keep dates, hashes, dependencies, and arithmetic deterministic;
3. expose missing evidence and model uncertainty;
4. require an accountable human rationale and action; and
5. export a hash-consistent, no-write local review record.

The next external validation step is five controller or accounting-manager
walkthroughs measuring time-to-evidence, time-to-decision, and whether CloseProof
surfaces missing support earlier than the participant's current workflow.
