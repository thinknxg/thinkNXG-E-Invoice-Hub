# Oman Fawtara: API

Base path `/api/method/thinknxg_einvoice_hub.api.oman.`; authentication `Authorization: token <api_key>:<api_secret>`
of a tenant user. Every endpoint resolves the caller's tenant, checks access and refuses a company whose compliance
profile is not an Oman engine. The generic endpoints (`api.outbound.*`, `api.status.*`, `api.inbound.*`) keep
working unchanged for Oman and UAE companies alike.

| Endpoint | Method | Access | Purpose |
| --- | --- | --- | --- |
| `validate_invoice` | POST | any tenant user | Dry run: normalise, enrich, run the hub rules and (when installed) the official Schematron. Stores nothing |
| `generate_document` | POST | any tenant user | Dry run: returns the PINT OM XML, the Invoice UUID, the Seller UUID and the QR payload |
| `submit_invoice` | POST | Admin / API | Queue an invoice or credit note (same as `outbound.submit_invoice`) |
| `get_status` | GET | any tenant user | Lifecycle of one transaction, adds `tax_authority_reporting_status` |
| `get_document` | GET | any tenant user | Stored payload of an Oman transaction (default: the PINT OM XML) |
| `process_inbound` | POST | Admin / API | Register a PINT OM document received from the provider |
| `get_country_profile` | GET | any tenant user | Code lists, transaction types, substitute participant IDs, effective settings (no secrets) |

Parameters: `invoice` (canonical JSON), `company` (profile ID, VATIN or legal name; optional when the tenant has one
company), `tenant` (name or code; optional when the user has one tenant).

## validate_invoice / generate_document response

```json
{
  "success": false,
  "country": "OM",
  "profile": "om_pint_om",
  "validation_status": "FAILED",
  "errors": [
    {"severity": "Error", "rule_id": "EIH-OM-016", "field_path": "supplier.tax_id",
     "message": "Supplier VATIN 'OM12345' must be 'OM' followed by 10 digits"}
  ],
  "warnings": [],
  "canonical": {"...": "normalised invoice (validate_invoice only)"}
}
```

`generate_document` adds, on success: `document` (XML), `document_uuid` (BTOM-002), `seller_uuid` (BTOM-004, B2C and
profit margin) and `qr_base64`. Official Schematron findings use the official rule IDs (for example `CL-08-OM-HS`)
with the XPath location as `field_path`.

## Example

```bash
curl -X POST https://<site>/api/method/thinknxg_einvoice_hub.api.oman.validate_invoice \
  -H "Authorization: token <key>:<secret>" -H "Content-Type: application/json" \
  -d "{\"company\": \"OM1100003554\", \"invoice\": $(cat samples/oman/standard_invoice/1_input.json)}"
```

## Status fields (get_status)

| Field | Meaning for Oman |
| --- | --- |
| `status` | overall: ... Submitted, Delivered, **Reported** (final when no Peppol delivery is expected), Rejected ... |
| `validation_status` | hub rules and official Schematron |
| `asp_submission_status` | accepted / rejected by the accredited provider |
| `fta_status` = `tax_authority_reporting_status` | TDD accepted (Reported) or rejected by the Tax Authority's access point |
| `delivery_status` | Peppol delivery to the buyer's provider; Not Applicable for B2C / export |
| `document_uuid`, `country_code` | Invoice UUID (BTOM-002) and OM |

`status.list_transactions` accepts `country=OM`; the dashboard API `services.monitoring.get_dashboard` accepts
`country` and `status`.
