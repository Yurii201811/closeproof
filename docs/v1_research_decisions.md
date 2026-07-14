# v1 research decisions

This note records how market research affected the product. It is not a market-
size study. Reddit items are practitioner anecdotes from a small, self-selected
sample and are treated as problem signals, not representative evidence.

## Repeated workflow pain signals

Recent bookkeeping discussions describe the time sink as missing receipts and
unknown transactions more than the final mechanical match. Practitioners still
verify exceptions, tie the ending balance to the statement, and sometimes use a
staging sheet to avoid accidental duplicates. Close discussions likewise point
to evidence collection, reconciliation ownership, and onboarding friction.

Sources sampled:

- [bank-reconciliation day-to-day discussion](https://www.reddit.com/r/Bookkeeping/comments/1tff5me/bookkeeping_software_for_bank_reconciliation/)
- [reconciliation cleanup discussion](https://www.reddit.com/r/Bookkeeping/comments/1t9rgse/bookkeeping_software_that_feels_less_painful_for/)
- [bookkeeping pain discussion](https://www.reddit.com/r/Bookkeeping/comments/11hd9zc)
- [accounting automation during close](https://www.reddit.com/r/Accounting/comments/1optybf/what_accounting_automation_tools_actually_save/)

The v1 response is therefore exception-first rather than chat-first:

- collect and hash evidence before extraction;
- make missing evidence an explicit resumable stage;
- suggest matches but retain statement tie-out and human review;
- combine repeated risk signals into one priority case;
- preserve a review packet and source hashes instead of silently posting;
- keep setup progressive and show current work first;
- provide Guided and Expert views over the same facts.

## Open-source patterns considered

[ERPNext](https://github.com/frappe/erpnext), [Odoo](https://github.com/odoo/odoo),
and [Frappe Books](https://github.com/frappe/books) demonstrate the value of
integrated accounting records, extensible ERP modules, and approachable local
or offline workflows. No source code or product assets were copied.

The architectural decision is an adapter control plane rather than another
embedded ledger: provider capabilities are declared explicitly, source records
stay attributable to their system, reads pass one binding gateway, and writes
remain forbidden. This supports Fortnox today at the contract/dry-run boundary
and leaves NetSuite, Oracle, SAP, Odoo, SIE, and CSV as honest extension points.

## Compliance and automation decision

Swedish official material requires continuous bookkeeping, supporting evidence,
ordered and protected accounting information, and accountable business
ownership. Those requirements rule out an invisible autonomous bookkeeper.
They support an autonomous preparation system with deterministic stop rules and
identified human decisions.

Primary references:

- [Skatteverket: Bokföring – vad kräver lagen?](https://www.skatteverket.se/foretagochorganisationer/startaochdrivaforetag/bokforingochbokslut/bokforingvadkraverlagen.4.18e1b10334ebe8bc80005195.html)
- [Bokföringsnämnden: Vägledningar](https://www.bfn.se/redovisningsregler/vagledningar/)
- [Skatteverket: fakturering and preservation](https://www.skatteverket.se/foretagochorganisationer/moms/saljavarorochtjanster/fakturering.4.58d555751259e4d66168000403.html)

The resulting principle is: automate collection, checking, matching, drafting,
explanation, and evidence packaging; require humans for judgment, approval,
communication, filing, payment, and every consequential external action.
