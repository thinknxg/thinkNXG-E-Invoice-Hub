# Release notes

## 0.3.1 (2026-11-21) - UAE PINT AE 1.0.5 fix release

Fixed
* UAE output now passes the official Peppol PINT AE 1.0.5 Schematron (billing and self-billing) and the UBL 2.1
  XSD on all 15 fixtures. In 0.3.0 every document failed 8 to 14 official rules (gap report R9). The generator
  now writes:
  * the unique identifier (BTAE-07)
  * AED line amounts and line VAT (BTAE-10 / BTAE-08)
  * item description, price base quantity and gross price
  * the legal registration authority
  * the foreign-currency exchange rate, AED tax total and AED total (BTAE-04 / BTAE-20)
  * mandatory payment means
  * credit note reason (BTAE-03), with the preceding-invoice rule for volume discounts
  * category-specific percent and exemption handling
  * the VAT point date only where allowed
* Self-billed out-of-scope documents use 480 / 81 (official self-billing code lists), not 389 / 261.
* Inbound UAE parsing reads the new fields and recognises self-billing by CustomizationID.

Added
* Optional official PINT AE Schematron in the pipeline (`schematron_dir`, `selfbilling_schematron_dir`,
  `official_validation` in the UAE Compliance Profile's engine settings), as for Oman.
* `compliance/uae/codes.py` with the official 1.0.5 code lists; the country profile lists them.
* Canonical fields:
  * `references.credit_reason_code` / `credit_reason` (same as Oman)
  * `document.invoice_period`
  * `legal_registration_authority`
  * line `item_type`, `rcm_goods_type`, `standard_item_id`, `service_accounting_code`
* Company Integration Profile field *Legal Registration Authority*.
* Official predefined buyer addresses applied for exports (9900000099) and deemed supplies (9900000097) when the
  ERP sends no buyer address.
* EIH-AE checks for every official rule the fixtures exercise; each names the official rule and the canonical field.
* `tests/test_uae.py` (26 tests; official Schematron and XSD cases run when the resources are set),
  `tests/uae_fixtures.py`, `tests/bench_uae.py` (34 bench checks), `docs/UAE_PINT_AE_VALIDATION.md`.
* Shared Schematron runner `compliance/shared/schematron.py` (the Oman module re-exports it; Oman behaviour unchanged).

Changed (upgrade impact; see docs/UAE_PINT_AE_VALIDATION.md section 5)
* UAE XML changes for every document; goldens regenerated deliberately.
* Stricter hub checks. These invoices now stop before submission instead of being rejected by the official rules:
  * missing seller legal registration or authority
  * credit notes without a reason code
  * exempt supplies without a DL8.46 code
  * credit transfer without an IBAN
  * no due date when an amount is payable
  * non-5% standard rate
  * malformed TRN
  * missing subdivision
* The shared test invoice and `samples/canonical_invoice.json` now carry the data PINT AE requires.

Known issues
* No UAE ASP sandbox or the FTA has received the new documents; Schematron pass is not ASP acceptance.
* Free-trade-zone (flag 1) and disclosed-agent billing (flag 6) documents are refused (EIH-AE-064):
  the generator does not produce the beneficiary / principal parties yet.
* PINT AE 1.0.3 (superseded) is not targeted. ASPs still on 1.0.4 need `service_accounting_code` on service lines.

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
* UAE output does not pass the official PINT AE Schematron (pre-existing; see docs/OMAN_GAP_REPORT.md R9). Fixed in 0.3.1.
