# ASP integration guide

## Three separate facts per provider

The **UAE Accredited Service Provider** directory keeps them apart:

1. Accreditation Status - what the Ministry of Finance directory says (86 entries loaded from the
   page dated 11/11/2026; re-check the official page, it changes).
2. Integration Status - Not Started, Skeleton - Pending API Documentation, In Development,
   Sandbox Tested, Production Verified.
3. Sandbox Tested / Production Verified - ticked by an administrator after real tests. Nothing is
   ticked on installation.

Being in the directory does not mean a connector exists.

## Onboarding a REST-based ASP without code

1. Get the provider's API documentation and sandbox credentials.
2. Create an **ASP REST API Configuration** (hub administrators create shared ones; tenant
   administrators create their own).
3. Create an **ASP Connection** with adapter `rest_config` (or pick the provider in "Accredited
   Service Provider"), link the configuration and enter the tenant's credentials. Credentials on
   the connection override the defaults on the configuration.
4. Press **Test Connection**, submit a test invoice, check **Integration Log**.
5. Update the directory entry's integration status when sandbox tests pass.

### Authentication types

| Type | Fields used |
| --- | --- |
| None | - |
| API Key | API Key, API Key Header (default `X-API-Key`), API Key Prefix |
| Bearer Token | API Secret (the token) or Static Authorization Header |
| OAuth2 Client Credentials | Client ID, Client Secret, Token URL, Scope, token/expiry response paths |
| OAuth2 Authorization Code | as above plus Refresh Token; the hub uses the refresh-token grant. A rotated refresh token returned by the provider is not yet written back |
| Basic | Username, Password |
| Custom Header | Custom Authentication Headers JSON, e.g. `{"X-Auth": "Key {api_key}"}` |
| HMAC-SHA256 | API Secret, signature/timestamp header names, signing template (`{timestamp}.{method}.{path}.{body}`), hex or base64 |
| JWT | HS256 token signed with API Secret; issuer = Client ID; extra claims JSON |
| Plugin | a function registered through the `einvoice_hub_rest_auth_plugins` hook |

### Endpoints

One row per operation: Verify Credentials, Get Participant, Register Participant, Validate Invoice,
Submit Invoice, Submit Credit Note, Submit Self-Billed Invoice, Get Invoice Status, Get Reporting
Status, Get Delivery Status, Download XML, Download PDF, Get Incoming Invoices, Register Webhook,
Get Webhook Subscription, Custom Operation. URL placeholders: `{document_id}`, `{participant_id}`,
`{tin}`. If no credit-note endpoint is configured, credit notes go to Submit Invoice.

### Request mapping

`Source Field` reads from this context: `invoice.*` (canonical invoice), `metadata.*` (transaction,
invoice_number, sender_id, receiver_id), `document` (compliance XML), `document_base64`,
`participant.*`, `idempotency_key`, or dynamic values `$now`, `$today`, `$timestamp`, `$uuid`.
Arrays: `invoice.lines[].quantity` -> `items[].qty`. With no mapping rows for an operation the
payload chosen by the connection's Payload Format is sent as the body.

Transformations (chain with `|`): `upper`, `lower`, `strip`, `digits`, `date:<strftime>`,
`decimal:<places>`, `number:<places>`, `integer`, `bool_yn`, `bool_10`, `base64`, `map:{json}`,
`prefix:<text>`, `suffix:<text>`, `uae_tax_code`, `json`, `const:<value>`. More can be registered
through the `einvoice_hub_rest_transformations` hook. Conditions: `path == value`, `path != value`
or `path` (exists).

### Response mapping

Map provider fields to: success, asp_document_id, submission_reference, submission_status,
fta_status, fta_reference, delivery_status, delivery_reference, error_code, error_message, xml_url,
pdf_url, timestamp, invoice_mls_code, tdd_mls_code. The two MLS fields take Peppol Message Level Status codes
(AP / AB / RE); the Oman engine turns the invoice MLS into Peppol delivery and the TDD MLS into tax-authority
reporting. Use `map:{...}` to translate the provider's status words into ACCEPTED /
REJECTED / PENDING, PENDING / REPORTED / REJECTED and PENDING / DELIVERED / FAILED.

### Webhooks and polling

Webhook URL: `/api/method/thinknxg_einvoice_hub.api.webhooks.asp?connection=<ASP Connection>`.
Verification: HMAC-SHA256 (header configurable), Standard Webhooks, Shared Secret, JWT (HS256).
The signature header cannot be `Authorization`. Providers without webhooks are polled: statuses
every 15 minutes while any outcome is open, incoming invoices when a Get Incoming Invoices endpoint
is configured.

## Wafeq preset

A shared configuration built from Wafeq's public documentation is installed (`wafeq`). Verified
from the documentation: base URL, `Authorization: Api-Key`, `x-ae-taxpayer-id`, invoice / credit-note /
validate / get endpoints, `Idempotency-Key`, status vocabularies, Standard Webhooks. Not verified:
anything at runtime. It has never been run against the Wafeq sandbox, and value formats such as
`tax_category` are assumptions. Treat it as a starting point.

## Writing a dedicated adapter

Subclass `ConfiguredRestAdapter` (or `BaseASPConnector`), override only what differs, register it
in `asp_connectors/adapter_registry.py` or through the `einvoice_hub_asp_adapters` hook, and declare
capabilities truthfully.

## Oman accredited providers

Under the Oman model the accredited provider (C2) validates the PINT OM invoice, sends it over Peppol to the buyer's
provider (C3), builds the Tax Data Document and sends it to the OTA access point (C5). The hub submits the PINT OM
XML (or the provider's JSON, through request mappings) and tracks two MLS results. No Oman provider adapter exists
yet: connect one with a REST API Configuration once its API documentation is available, map its MLS / status fields
as above, and test it in the provider's sandbox (`OMAN_FAWTARA_TESTING.md`). `tests/mock_oman_provider.py` is a
test double only.
