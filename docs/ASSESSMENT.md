# Platform and reference-repository assessment (2026-11-12)

## 1. Existing platform (0.1.1) before this release

Architecture: `ERP connectors -> canonical invoice -> compliance engine -> ASP adapters`, with
framework-free connectors, adapters and engines, and `core/`, `services/`, `api/` on top of thinkNXG
Framework v16. Working and bench-tested: canonical model and mapper, UAE PINT AE engine (baseline),
outbound and inbound pipelines, retry engine, reconciliation, signed webhooks, Universal API, tenant
isolation, ERPNext / thinkNXG ERP connector (not run against a live ERP), Universal API / Custom ERP
connector, sandbox and Generic REST (JSON options) ASP adapters.

Gaps against the enhancement brief: no UI-configurable REST contract (endpoints, auth types, mappings),
one overall status instead of separate ASP / FTA / delivery outcomes, no ASP directory, no provider
capability model beyond four flags, no XML/PDF retrieval, no integration log, no dashboard, no
Microvista integration, no webhook event de-duplication.

## 2. Reference repositories

Both were cloned and read at source level (MIT licence).

| | `ERPGulf/uae_erpgulf` (original) | `ERPGulf/einvoice_erpgulf` (successor) |
| --- | --- | --- |
| Last commit read | 2026-10-27 | 2026-11-10 |
| Shape | ERPNext app, UAE only | ERPNext app, country profiles (AE, OM, BE) + provider adapters |
| ASP adapters | Fynamics, Marmin, Suntech, Flick | Fynamics, Marmin, Suntech, Flick, A-Cube |
| Contract | `providers/base.py` | `core/base.py` `BaseAdapter`: token cache, `submit_invoice`, `parse_submit_response`, `get_document_status`, XML/PDF, webhook registration, participant lookup, incoming-invoice parsing; optional methods fall back to `_not_supported` |
| Registry | hard-wired | `core/registry.py`: countries and providers contributed through hooks, provider options synced into settings |
| Authentication | bearer tokens fetched per provider | same; token and expiry cached in the site cache; one adapter supports an API key |
| Payloads | built from Sales / Purchase Invoice documents | same (`_build_payload`, `sales_json.py`, `purchase_json.py`), plus UBL built by the country profile |
| Status sync | scheduler | `core/status_sync.py`, every 5 minutes, per-adapter "final status" sets |
| Webhooks | provider-specific guest endpoints | provider-specific guest endpoints inside each adapter; HMAC checks in the A-Cube and Marmin adapters |
| Incoming invoices | DocType + conversion | `core/incoming.py`, creates Purchase Invoices |
| Automated tests | generated stubs only | generated stubs only (4 files of 22 lines); testing is a manual UI guide |

### Reusable conceptually (adopted)

* One adapter contract with optional operations that fail explicitly when a provider lacks them.
* Hook-based provider registration; cached access tokens kept out of the database.
* Separate "final status" handling per outcome and scheduled status polling.
* Not using the `Authorization` header for webhook secrets (the framework consumes it).
* Blocking re-submission once a provider document ID exists.

### Not reused

* Payload builders and validations that read ERPNext Sales Invoice / Company / Customer documents.
  The hub's adapters receive the canonical invoice and never see an ERP document.
* Provider endpoints and field names found in those adapters (for example the Fynamics hosts and
  `/invoicerequest`). They are evidence that such an API exists, but they were not verified against
  provider documentation or a sandbox here, so no Flick, Marmin, Suntech or Fynamics configuration
  is shipped. Each can be entered as an ASP REST API Configuration and tested when credentials exist.
* Per-provider webhook endpoints: the hub has one endpoint per connection with configurable verification.

## 3. Provider documentation found

| Provider | Public API documentation | Used for |
| --- | --- | --- |
| Microvista | None found (provider website has marketing content only) | Nothing. Skeleton + checklist only |
| Wafeq | https://wafeq-e-invoicing-asp.readme.io/docs (authentication, submit, track, webhooks pages read) | Reference for the REST engine design and a configuration preset, flagged untested |
| Others | Not researched in this release | - |

## 4. Result

See `README.md` ("What is in this release") for the implemented scope and per-provider readiness.
