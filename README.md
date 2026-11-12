# thinkNXG E-Invoice Hub

Universal e-invoicing integration platform built on thinkNXG Framework v16.

It is ERP-independent and ASP-independent: any ERP connects once to the hub, any
Accredited Service Provider (ASP) connects once to the hub, and a canonical invoice
model sits between them. No ERP ever integrates directly with an ASP.

```
ERP connectors  ->  Universal Invoice Engine  ->  Compliance Engine  ->  ASP connectors  ->  Peppol network
   (inbound and outbound, both directions)
```

The UAE (Peppol PINT AE) is the first country implementation, not the identity of
the product. Further countries are added as compliance engines.

## What is in this release (0.2.0)

| Area | Status |
| --- | --- |
| Canonical invoice model, mapper, UAE PINT AE engine (baseline; see "Compliance scope") | Implemented, unit tested |
| Outbound / inbound pipelines, retry engine, reconciliation, Universal API, signed webhooks | Implemented, tested on a v16 bench |
| Independent lifecycle tracking: internal validation, ASP submission, FTA reporting, Peppol delivery, ERP sync | Implemented, tested on a v16 bench with a mock ASP |
| Configurable REST engine: ASP REST API Configuration (auth, endpoints, headers, request / response mapping, webhooks) | Implemented, unit tested and bench tested against a mock ASP |
| UAE Accredited Service Provider directory (86 entries from the Ministry of Finance page dated 11/11/2026) | Implemented |
| Integration Log (masked), XML / PDF retrieval, webhook event de-duplication, per-transaction processing lock | Implemented, bench tested with a mock ASP |
| Universal Integration Dashboard page, Microvista Settings form | Implemented; the data APIs are tested, the screens have not been opened in a browser |
| Multi-tenant isolation, including REST configurations and integration logs | Implemented, bench tested |

### ASP adapters and their readiness

| Provider | Adapter | Readiness |
| --- | --- | --- |
| Sandbox (simulated) | `sandbox` | Works; transmits nothing |
| Any REST-based ASP | `rest_config` + ASP REST API Configuration | Engine tested against a mock ASP only; each real provider needs its contract entered and sandbox-tested |
| Microvista Technologies LLC (157529) | `microvista` | Skeleton. No public API documentation found; refuses to transmit. See `docs/MICROVISTA_SETUP.md` |
| Wafeq FZ-LLC (129932) | `wafeq` + preset configuration | Preset built from public documentation; never run against the Wafeq sandbox |
| Flick, Marmin, Suntech, Fynamics | `flick`, `marmin`, `suntech`, `fynamics` | Selectable, no contract configured, refuse to transmit |
| Avalara, Comarch, Pagero, ClearTax, Cygnet, EDICOM | placeholders | Not implemented |
| Earlier JSON-options adapter | `generic_rest` | Kept for backward compatibility |

No provider is production verified.

### ERP connectors

| ERP | Connector | Readiness |
| --- | --- | --- |
| ERPNext / thinkNXG ERP | `erpnext` | Implemented; not yet run against a live ERP site |
| Any ERP with REST / webhooks / JSON | `custom` + Mapping Configuration | Implemented; push mode bench tested |
| SAP S/4HANA, SAP Business One, Oracle Fusion, Oracle EBS, Microsoft Dynamics, Odoo, Zoho Books, Focus, Tally | catalogue entries | Not implemented; integrate through `custom` meanwhile |

Not built in this release: dedicated ERP connectors above, XML / CSV file intake for ERPs, a
drag-and-drop mapper, write-back of rotated OAuth refresh tokens, emission of the new optional
canonical fields beyond what the PINT AE generator already covers.

Documentation: `docs/ASSESSMENT.md`, `docs/ARCHITECTURE.md`, `docs/ASP_GUIDE.md`,
`docs/MICROVISTA_SETUP.md`, `docs/OPERATIONS.md`.

## Install

```bash
bench get-app /path/to/thinknxg_einvoice_hub      # or your git URL
bench --site <site> install-app thinknxg_einvoice_hub
bench --site <site> migrate
```

Installation creates three roles (E-Invoice Hub Admin, E-Invoice Hub Tenant Admin,
E-Invoice Hub User), the connector and provider catalogues, and the
`uae_pint_ae` compliance profile. The scheduler and background workers must be running.

Run the framework-independent tests without a bench:

```bash
python -m unittest thinknxg_einvoice_hub.tests.test_engine \
  thinknxg_einvoice_hub.tests.test_rest_engine thinknxg_einvoice_hub.tests.test_presets \
  thinknxg_einvoice_hub.asp_connectors.uae.microvista.tests.test_microvista
```

## Quick start with the sandbox provider

1. **Integration Tenant** - create a tenant and add its users (access level Admin, User or API).
2. **ASP Connection** - provider `sandbox`, environment Sandbox.
3. **ERP Connection** - connector `custom` (push mode needs no URL) or `erpnext`.
4. **Company Integration Profile** - legal name, TRN, address, the two connections and the
   `uae_pint_ae` compliance profile. The participant ID (`0235:<TIN>`) is derived from the TRN.
5. Create an API key for a tenant user (access level API) and submit the sample invoice:

```bash
curl -X POST https://<site>/api/method/thinknxg_einvoice_hub.api.outbound.submit_invoice \
  -H "Authorization: token <api_key>:<api_secret>" -H "Content-Type: application/json" \
  -d "{\"company\": \"100000000000003\", \"invoice\": $(cat samples/canonical_invoice.json)}"
```

The sandbox never transmits anything. Invoice numbers containing `REJECT`, `TIMEOUT` or
`PENDING` exercise rejection, the retry engine and delayed delivery. When you resubmit the
sample with a different invoice number, change `references.erp_document_id` as well: a
repeat of the same ERP document ID deliberately returns the existing transaction.

## Universal Integration API

Base path: `/api/method/thinknxg_einvoice_hub.api.`  Authentication: `Authorization: token <key>:<secret>`.

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `outbound.submit_invoice` | POST | Submit a canonical invoice, or raw ERP JSON mapped by the connection's Mapping Configuration |
| `outbound.fetch_and_submit` | POST | Hub pulls one document from the ERP and transmits it |
| `outbound.validate_invoice` | POST | Dry run: normalise and validate without storing or sending |
| `status.get_status` | GET | Status by hub transaction, ERP document ID or invoice number |
| `status.list_transactions` | GET | Filtered list for the caller's tenant |
| `status.get_document` | GET | Stored payload (canonical JSON, compliance XML, ASP response ...) |
| `status.reprocess` / `status.cancel` / `status.refresh_status` | POST | Operate on a transaction |
| `inbound.receive_document` | POST | Authenticated intake of a received document |
| `asp.providers` | GET | ASP directory with accreditation, integration status and production readiness |
| `asp.verify_credentials` | POST | Check an ASP connection's credentials (tenant admin) |
| `asp.readiness` | GET | Readiness report of a contract-pending provider such as Microvista |
| `asp.fetch_document` | POST | Retrieve the XML or PDF the ASP holds for a submitted document |
| `webhooks.erp?connection=<id>` | POST | Signed ERP events (the connection goes in the URL) |
| `webhooks.asp?connection=<id>` | POST | Signed ASP status callbacks and inbound documents |

Webhooks must carry an HMAC-SHA256 signature of the raw body made with the connection's
webhook secret: `X-EIH-Signature: <hex>` (ERPNext / thinkNXG ERP webhooks send
`X-Frappe-Webhook-Signature`, which is also accepted). Unsigned requests are rejected and
their bodies are not stored.

Transaction statuses: Received, Normalized, Validated, Validation Failed, Submitted,
Delivered, Rejected, Retrying, Failed, Duplicate, Cancelled.

## Canonical invoice

The full field list is documented in `thinknxg_einvoice_hub/canonical/invoice_schema.py`;
`samples/canonical_invoice.json` is a working example. The original ERP payload, the
canonical form, the compliance document and every ASP response are stored as immutable
Invoice Payload records, so source data is never lost.

Tax categories: STANDARD, ZERO_RATED, EXEMPT, OUT_OF_SCOPE, REVERSE_CHARGE, MARGIN_SCHEME.
Document types: INVOICE, CREDIT_NOTE, SELF_BILLING_INVOICE, SELF_BILLING_CREDIT_NOTE,
each as a TAX or COMMERCIAL document (`document.invoice_kind`).

## Connecting ERPNext / thinkNXG ERP

ERP Connection: connector `erpnext`, base URL of the ERP site, API key and secret of an
integration user that can read Sales Invoice, Address and Country and create Comment and
Purchase Invoice. Then choose one or both:

* **Webhook** - in the ERP create a Webhook on Sales Invoice (`on_submit`) pointing to the
  URL shown on the ERP Connection form, with the same secret enabled as webhook secret.
* **Scheduled retrieval** - tick "Retrieve Pending Invoices Automatically"; submitted Sales
  Invoices modified since the last run are collected every 10 minutes.

Statuses are written back as a comment on the Sales Invoice, and optionally into custom
fields. Inbound invoices become draft Purchase Invoices. Optional Extra Configuration keys
are listed at the top of `erp_connectors/erpnext/connector.py`.

## Connecting any other ERP

Use connector `custom`. The ERP posts canonical JSON, or its own JSON plus a Mapping
Configuration (header and line rules with transforms: Date, Number, Value Map, Constant ...).
Pull mode and status callbacks are configured through Extra Configuration; see
`erp_connectors/custom/connector.py`.

## Connecting an ASP

Create an **ASP REST API Configuration** from the provider's API documentation and an ASP Connection
with adapter `rest_config`; `docs/ASP_GUIDE.md` walks through authentication types, endpoints,
mappings and webhooks. The status API returns ASP submission, FTA reporting and Peppol delivery as
separate fields.

## Adding connectors, adapters and countries

Ship them in a separate app and register them in its `hooks.py`:

```python
einvoice_hub_erp_connectors = {"netsuite": "my_app.connectors.NetSuiteConnector"}
einvoice_hub_asp_adapters = {"my_asp": "my_app.adapters.MyASPAdapter"}
einvoice_hub_compliance_engines = {"sa_zatca": "my_app.engines.ZatcaEngine"}
```

Subclass `BaseERPConnector`, `BaseASPConnector` or `BaseComplianceEngine`, declare the
`capabilities` the class really supports, and run `bench migrate` to refresh the catalogues.
Classes are loaded only from installed code, never from a path stored in the database.

## Multi-tenancy and security

* Every tenant-scoped record carries a tenant; users see only their tenants' records in
  lists, forms and the API. Hub administrators see everything.
* Credentials and webhook secrets are stored in encrypted password fields.
* Outbound HTTP calls to private or local network addresses are refused unless
  "Allow Connections to Private Network Hosts" is enabled in E-Invoice Hub Settings
  (enable it only for single-organisation deployments with an on-premise ERP).
* Inbound XML with DTD or entity declarations is refused.

## Compliance scope (read before going live)

* The UAE engine is a PINT AE-aligned baseline (specification 1.0.3 identifiers). Its checks
  use the hub's own rule IDs (`EIH-AE-*`) and catch data problems early; they are not the
  official PINT AE Schematron.
* The generated XML has not been validated against the official PINT AE validation
  artefacts or any ASP. Do this with your chosen ASP before production use, and extend
  `compliance/uae/` where their validation reports gaps.
* Authoritative validation, digital signing, Peppol transmission and tax data reporting to
  the Federal Tax Authority are the Accredited Service Provider's role.
* Predefined network endpoints for special cases (exports, buyers not yet onboarded,
  deemed supplies) are not applied automatically; supply `customer.tin` for those cases
  according to current Ministry of Finance guidance.
* This app does not hold or imply any regulatory accreditation.

## Scaling note

Connectors, adapters and engines are plain Python with no framework or database access;
only `core/`, `services/` and `api/` use the framework. Transaction processing can
therefore move to dedicated workers or a separate service later without rewriting them.
