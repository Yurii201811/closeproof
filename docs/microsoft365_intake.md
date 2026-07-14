# Microsoft 365 Intake

This design keeps Microsoft 365 intake local-first until explicit Graph
credentials and tenant boundaries exist. The current implementation uses local
sample files only. It copies approved local files into controlled local storage
when a storage path is supplied. It does not read private mail, connect to
OneDrive, send email, move files, delete files, or store secrets.

## Current Local Prototype

Implemented modules:

- `accounting_agent.intake.models`: shared source and case dataclasses.
- `accounting_agent.intake.local`: local/mock source factories and folder scan.
- `accounting_agent.intake.store`: SQLite tables for normalized intake cases,
  extraction tasks, client mapping rules, and audit events.
- `accounting_agent.documents.hash`: SHA-256 file hashing.
- `accounting_agent.documents.invoice_metadata`: conservative text-fixture
  invoice metadata extraction for duplicate checks.

Run the local sample scan:

```bash
python -m accounting_agent.cli scan-intake-folder \
  --folder fixtures/microsoft365_intake \
  --db .local/accounting_agent.sqlite \
  --storage .local/intake_documents
```

The scan creates one `document_intake_cases` row per new source file, safely
copies the file to `.local/intake_documents`, stores the source metadata and
SHA-256 hash, and enqueues an `extract_document` row in `extraction_tasks`.
Running the same scan again is idempotent for the same source reference and
file hash.

## Intake Interface

All source adapters should normalize into `IntakeSource`:

| Source | Factory | Required identity | Required metadata |
| --- | --- | --- | --- |
| Outlook email attachment | `outlook_attachment_source(...)` | message id and attachment id | sender, sender domain, received date, subject |
| OneDrive folder file | `onedrive_file_source(...)` or `scan_folder(...)` | drive id and item id when real; local path for mock | folder path, item id, drive id, creator, modified date |
| Manual local upload | `manual_upload_source(...)` | resolved local path | uploader and optional note |
| Future Teams message/file | `teams_message_file_source(...)` | team id, channel id, message id, file id | sender and Teams identifiers |

Every adapter must preserve:

- source type and source reference
- original path or Graph identity
- stored path or reference path
- file name, content type, size, SHA-256 hash
- sender or creator
- received or modified date
- client mapping result
- invoice metadata if available
- duplicate status
- append-only audit events

## Duplicate Detection

The prototype checks duplicates in two layers:

- Exact file duplicate: same SHA-256 hash.
- Possible invoice duplicate: same client, supplier, invoice number, invoice
  date, gross amount, and currency when those fields can be extracted.

A duplicate still becomes an intake case and still receives an extraction task.
The case records `duplicate_of_case_id` and `duplicate_reasons` so later
proposal logic can block or route it for review.

## Client Mapping Placeholder

Client mapping rules live in SQLite as `client_mapping_rules` and currently
support:

- `sender`: exact normalized sender email
- `domain`: sender email domain
- `folder`: substring match against folder path

Unmatched sources use `client_id="unmapped"` so intake does not silently assign
private documents to the wrong client. A production version should replace this
placeholder with explicit client-owned folders, allowed senders/domains, and a
human review queue for unmapped documents.

## Real Microsoft Graph Integration Later

Real Microsoft 365 intake must be added as a separate adapter behind explicit
configuration, for example:

- `M365_GRAPH_ENABLED=true`
- tenant id and client id in local config
- secrets only in the operating system keychain or a secret manager
- an allowlist of mailbox folders, OneDrive folders, and client mappings
- a dry-run mode that lists candidate source identities without downloading
  content

Do not enable live Graph reads from defaults. The local mock path must keep
working without any cloud credentials.

### Outlook

Use Microsoft Graph mail APIs only after the mailbox, folder, and permission
boundary are explicit. Normalize each attachment as:

- source reference: `outlook://messages/{message_id}/attachments/{attachment_id}`
- source metadata: sender, sender domain, received date, subject, message id,
  internet message id if available, attachment id, attachment name, content type,
  size, and mailbox/folder id

Prefer read-only mail access. Do not request `Mail.Send` for intake. The adapter
should list approved folders/messages, list attachments, download only approved
file attachments to a local temp path, pass that temp path into
`LocalIntakeProcessor.ingest`, and then leave the original message untouched.

### OneDrive

Use OneDrive/SharePoint file APIs only for approved drives or folder roots.
Normalize each file as:

- source reference: `onedrive://drives/{drive_id}/items/{item_id}`
- source metadata: drive id, item id, parent reference, path, web URL if safe to
  store, eTag/cTag, created/modified timestamps, creator/modifier, size, and
  download audit timestamp

Use stable drive/item identifiers for source identity. Path should be preserved
for operator readability, but it should not be the only identity because files
can be renamed or moved.

### Teams

Teams support should stay future-only until there is a concrete Lena workflow.
When added, Teams files should normalize into the same interface using message
and file identifiers, then resolve the backing file as a DriveItem where Graph
represents it that way. Teams chat/message permissions can be broader and more
sensitive than folder intake, so this should require a separate explicit
configuration and review.

## Safety Rules

- No live Microsoft 365 connection unless config explicitly enables it.
- No private email/document processing by default.
- No email sending from intake.
- No deleting, moving, or marking originals as processed.
- No secrets in repo files, fixtures, logs, or SQLite rows.
- Obsidian may be a generated mirror later, but it is not the operational queue.

## References

- Microsoft Graph Outlook mail API overview:
  https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview
- Microsoft Graph attachment resource:
  https://learn.microsoft.com/en-us/graph/api/resources/attachment
- Microsoft Graph OneDrive file storage overview:
  https://learn.microsoft.com/en-us/graph/onedrive-concept-overview
- Microsoft Graph DriveItem addressing:
  https://learn.microsoft.com/en-us/graph/onedrive-addressing-driveitems
- Microsoft Graph Teams messaging APIs:
  https://learn.microsoft.com/en-us/graph/teams-messaging-overview
