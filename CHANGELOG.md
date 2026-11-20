# Release notes

## 0.3.0 (2026-11-21) - Oman Fawtara

Added
* Oman compliance engine `om_pint_om` (Peppol PINT OM Billing / Self-Billing 1.0.1): invoices, credit notes,
  self-billed documents, B2C simplified invoices, export, foreign currency; Invoice UUID and Seller UUID by the
  published OTA method; QR payload; 0248 participant IDs and substitute participants.
* Oman validation (EIH-OM-*) mapped to the official rules, and optional official Schematron validation in the
  pipeline (`official_validation`, Saxon).
* MLS status mapping: invoice MLS -> Peppol delivery, TDD MLS -> tax-authority reporting; REST mapping targets
  `invoice_mls_code`, `tdd_mls_code`; overall status "Reported" for flows without Peppol delivery.
* `api.oman.*` endpoints; dashboard country / transaction-status filters and Oman counts.
* Compliance Profile: country code, environment, engine settings, effective-dated Tax Rules table.
* Company profile: address line 3; contact fields used on invoices.
* ERPNext connector Oman options (issue time, item fields, credit reason, B2C flag, reason codes).
* Credit notes take the original invoice UUID and date from hub records.
* Patch `v0_3.country_code_backfill`; tests (38 unit, 28 bench checks), samples, Oman documentation.

Fixed
* Inbound documents in tenants with companies in several countries are parsed by the engine matching the
  document's CustomizationID (previously the first engine alphabetically).

Unchanged
* UAE PINT AE output (byte-identical regression goldens).

Known issues
* No accredited Oman provider integrated or sandbox-tested; mock provider only.
* UAE output does not pass the official PINT AE Schematron (pre-existing; see docs/OMAN_GAP_REPORT.md R9).
