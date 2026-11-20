# Multi-Country Architecture

```
ERP systems
    │  ERP connectors (erpnext, custom, ...)
    ▼
Universal canonical invoice (schema 1.0)          canonical/
    ▼
Invoice processing engine                          services/invoice_service.py
    │  company profile -> compliance profile -> engine code
    ├──────────────────────────────┐
    ▼                              ▼
UAE engine  uae_pint_ae            Oman engine  om_pint_om             (future: further engines)
PINT AE 1.0.5 / UBL 2.1            PINT OM 1.0.1 / UBL 2.1
    ▼                              ▼
ASP adapter (UAE provider)         ASP adapter (Oman provider)          asp_connectors/
    ▼                              ▼
UAE Peppol network + FTA           Oman Peppol network + OTA (via C5)   (external)
```

The core never tests for a country. Everything country-specific sits behind the engine interface and is selected
through the company's Compliance Profile, so one tenant can hold UAE and Oman companies side by side.

## Country engine interface (`compliance/base.py`)

| Method / attribute | Purpose |
| --- | --- |
| `code`, `country`, `country_code`, `standard`, `spec_version`, `tax_authority` | identity |
| `document_types`, `tax_categories`, `get_supported_document_types()`, `get_supported_tax_categories()` | capabilities |
| `get_country_profile()` | description plus effective settings |
| `normalize_invoice(inv)` | country-neutral normalisation + `enrich` |
| `enrich(inv)` | derive country identifiers (participant IDs, UUIDs, transaction types) |
| `validate(inv)` / `validate_invoice(inv)` | issue list `{severity, rule_id, field_path, message}` |
| `generate_document(inv)` | `{"content", "format", "media_type", "document_uuid"?}` |
| `validate_document(document, inv)` | optional check of the generated document (Oman: official Schematron) |
| `parse_document(content)` | received document -> canonical |
| `participant_id(party)` | network address |
| `tax_code(category)` | country category code |
| `parse_provider_response(resp)` | add country meaning to a provider result (Oman: MLS codes) |
| `map_transaction_status(raw)` | provider status word -> lifecycle value |
| `delivery_expected(inv)` | False when only tax reporting follows (Oman B2C / export) |
| `uses_document_uuid` | the hub keeps the document UUID and fills credit-note references from it |
| `profile_defaults` | seeded into the Compliance Profile on install |

Engines are plain Python: they receive a settings dict (Compliance Profile fields + Engine Settings JSON + Tax Rules)
and never touch the database.

## Shared, country-neutral pieces

* Canonical model and normaliser (amounts rounded to the currency's minor unit).
* UBL writer / safe parser (`compliance/shared/xml.py`).
* Processing pipeline, idempotency, locks, retry, reconciliation, ERP sync.
* Lifecycle fields: internal validation, provider submission, tax-authority reporting, Peppol delivery, ERP sync.
* ASP adapter contract, REST configuration engine, sandbox adapter.
* Tenant isolation, encrypted credentials, masked logs, signed webhooks.
* Inbound routing: in a multi-country tenant the engine is chosen from the document's CustomizationID.

## Adding a country

1. Create `compliance/<country>/` (or a separate app) with an engine class subclassing `BaseComplianceEngine`.
   Keep identifiers and code lists in a `constants.py` that settings can override.
2. Register it: built-in in `compliance/registry.py`, or from another app's `hooks.py`:
   `einvoice_hub_compliance_engines = {"sg_pint_sg": "my_app.engines.PintSGEngine"}`.
3. `bench migrate` creates its Compliance Profile from `profile_defaults`.
4. Add fixtures and tests: generated documents must pass the official validation artefacts of that country.
5. Add or configure a provider adapter for that country's accredited providers.
6. Document the specification with a source per requirement, as in `OMAN_FAWTARA_SPECIFICATION.md`.

No change to the core, the canonical schema version or the existing engines is needed. Singapore, Malaysia,
Australia / New Zealand and European PINT profiles are extensibility targets only; none is implemented.
