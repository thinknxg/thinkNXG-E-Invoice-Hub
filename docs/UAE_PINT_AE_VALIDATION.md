# UAE PINT AE 1.0.5: fix release 0.3.1

Up to 0.3.0 the UAE engine produced XML that the official Peppol PINT AE Schematron rejected
(8 to 14 fatal rule failures per document; see gap report R9). Release 0.3.1 rewrites the UAE
generator and the hub's UAE checks against **PINT AE 1.0.5 (Final, 2026-11-17)**, the current
release published by OpenPeppol for the UAE Peppol Authority.

This document says what changed, what evidence there is, what it does not prove, what
operators have to do when they upgrade, and how to roll back.

## 1. What "validated" means here

| Check | Result | Scope |
| --- | --- | --- |
| Official PINT AE 1.0.5 Schematron (billing and self-billing, compiled XSLT from the official `resources.zip`) | 0 errors, 0 warnings on all 15 fixtures and the 5 legacy test inputs | Run with Saxon by the unit tests (`AE_PINT_RESOURCES`) and inside the pipeline on the bench |
| PINT AE 1.0.4 rule set | 0 errors when service lines carry the service accounting code (BTAE-17) | 1.0.4 requires BTAE-17 for services; 1.0.5 made it optional |
| OASIS UBL 2.1 XSD | 15/15 schema-valid | `TestUBLSchema` (`UBL21_XSD_DIR`) |
| Bench pipeline (ingest → validate → generate → official Schematron → sandbox submit) | 34/34 checks on two sites | `tests/bench_uae.py` |
| Accredited Service Provider (ASP) | **Not tested** | No UAE ASP sandbox has received these documents |
| Federal Tax Authority | **Not tested** | Tax data reporting and signing are the ASP's role |

Passing the official Schematron is necessary, not sufficient. It is not acceptance by an ASP or the
FTA. Test with your ASP's sandbox before production.

PINT AE 1.0.3 is superseded and not targeted. Its rules differ on currency attributes and on payment
means for credit notes.

## 2. Official rules that failed before, and the fix

| Official rule | What was wrong in 0.3.0 | 0.3.1 |
| --- | --- | --- |
| ibr-193-ae | No unique identifier (BTAE-07) | `cbc:UUID`: ERP value if sent, otherwise a stable UUID v5 of seller TRN, type, number and date (the same document always gets the same UUID) |
| ibr-104-ae, ibr-194-ae | No AED line amount (BTAE-10) or line VAT (BTAE-08) | `cac:ItemPriceExtension` on every line; no BTAE-08 on exempt lines (ibr-163-ae) |
| ibr-125-ae | Item description dropped when it equalled the name | Always written (falls back to the item name) |
| ibr-126-ae, aligned-ibrp-004 | No price base quantity or gross price | `BaseQuantity` always; price `AllowanceCharge` with `BaseAmount` |
| ibr-150-ae, ibr-172-ae, ibr-173-ae | Seller legal registration not checked; no authority name | `schemeAgencyName` from the new `legal_registration_authority`; checked before submission |
| ibr-153-ae, ibr-159-ae, ibr-175-ae | Foreign-currency documents had no exchange rate or AED total | `TaxExchangeRate` (document currency → AED), an AED `TaxTotal`, and the `aedtotal-incl-vat` document reference (BTAE-20) |
| ibr-191-ae, ibr-192-ae | Payment means missing unless sent; credit transfer without IBAN not caught | Payment means always on invoices (`1` = instrument not defined when none is sent, with a warning); IBAN required for code 30 |
| ibr-055-ae, ibr-158-ae | Credit notes had no reason code (BTAE-03) | `DiscrepancyResponse`; preceding invoice left out for volume discount (`VD`) |
| ibr-124-ae, ibr-141-ae | VAT point date written on credit notes and when not earlier than the issue date | Written only on invoices and only when earlier |
| ibr-165-ae and the category rules | Line VAT not written; exempt reason codes not on lines; percent on E / O | Category-specific percent and reason handling for S, Z, E, O, AE, N |
| UNCL1001 (self-billing) | Self-billed out-of-scope documents used 389 / 261 | 480 / 81, per the official self-billing code lists |

Additions: item type (BTAE-13), reverse-charge goods type (BTAE-09) and GTIN, service accounting code
(BTAE-17), invoicing period with frequency of billing (IBT-008), and `TaxIncludedIndicator`. The official
predefined buyer addresses are used automatically: `9900000099` for exports to a buyer with no TIN, and
`9900000097` for deemed supplies. An ERP-supplied buyer address always takes precedence.

## 3. Canonical fields used by the UAE engine (new in 0.3.1, all optional in the model)

| Canonical field | PINT AE term | Required when |
| --- | --- | --- |
| `document.uuid` | BTAE-07 | Generated when absent |
| `document.invoice_period.{start_date,end_date,frequency_code}` | IBG-14, IBT-008 | Summary invoice (flag position 4) |
| `references.credit_reason_code`, `references.credit_reason` | BTAE-03 | Credit notes (381 / 81). Same field as Oman |
| `supplier/customer.legal_registration_authority` | BTAE-12 / BTAE-11 (TL), BTAE-19 / BTAE-18 (PAS) | Trade licence or passport |
| `lines[].item_type` | BTAE-13 (G / S / B) | Optional; G / B then need `commodity_code` (HS) |
| `lines[].exemption_reason_code` | IBT-121 (DL8.46.1–4) | EXEMPT lines, allowances and charges |
| `lines[].rcm_goods_type` | BTAE-09 (DL8.48.x) | REVERSE_CHARGE lines |
| `lines[].standard_item_id` (scheme 0160) | IBT-157 | REVERSE_CHARGE lines |
| `lines[].service_accounting_code` | BTAE-17 | Only for ASPs still validating with PINT AE 1.0.4 |

New Company Integration Profile field: **Legal Registration Authority**.

Code lists (credit reasons, exemption codes, RCM goods types, item types, billing frequencies,
payment means, legal registration types, transaction flags, predefined endpoints) are in
`compliance/uae/codes.py`. They are copied from the official 1.0.5 resources and exposed by the
country profile.

## 4. Hub checks (EIH-AE-*)

Each check names the official rule it anticipates, and reports the canonical field that needs fixing.

New in 0.3.1:
* 019–023: legal registration, type, authority, passport country, buyer identifier
* 024: tax currency
* 025: payment means defaulted (warning)
* 026: VAT point date
* 035/036: item type and HS code
* 044: exemption code
* 045/046: category combinations
* 047–049: reverse charge
* 060/061: credit reason
* 062/063: invoicing period and frequency
* 064: unsupported flags
* 065: delivery address
* 066: flags on out-of-scope documents

Now errors (previously warnings, or not checked):
* EIH-AE-006: exchange rate
* EIH-AE-007: due date when an amount is payable
* EIH-AE-013/014: subdivision for every address, and the emirate list for UAE addresses
* EIH-AE-016: TRN shape, 15 digits starting with 1 and ending with 03
* EIH-AE-042: standard rate other than 5%

When configured, the official Schematron runs after generation (`validate_document`), mirroring Oman:

```json
{"schematron_dir": "/opt/pint-ae-resources-1.0.5/billing",
 "selfbilling_schematron_dir": "/opt/pint-ae-resources-1.0.5/sb",
 "official_validation": "required"}
```

Set this in the UAE Compliance Profile's *Engine Settings*. `official_validation` is `off`,
`if_configured` (default: warning EIH-AE-090 when the rules are not installed) or `required`
(a missing rule set blocks submission). Saxon is needed: `pip install saxonche`. The official
rule files do not state their version, so keep the version in the folder name.

## 5. Upgrade impact (read before migrating)

0.3.1 stops documents earlier that the official rules already rejected, so some invoices that
used to pass the hub now fail validation, with a message naming the field:

1. **Company profiles**: fill Legal Registration ID, Type (`TL`, `EID`, `PAS`, `CD`) and, for a
   trade licence, *Legal Registration Authority* (for example the issuing economic department).
   Without them every invoice fails EIH-AE-019 / 020 / 021 (official ibr-150-ae / ibr-181-ae / ibr-172-ae).
2. **Credit notes** need `references.credit_reason_code`. In ERPNext, set `credit_reason_field` and / or
   `default_credit_reason_code` on the ERP Connection (values DL8.61.1.A–E or VD).
3. **Exempt supplies** need a DL8.46.x code. In ERPNext, use a `tax_category_map` entry with
   `exemption_reason_code`.
4. **Credit transfer** (payment means 30) needs the IBAN. **Invoices** with an amount due need a due date.
5. **Foreign buyers** need a state or region in their address (ibr-144-ae). Reverse-charge lines need the
   goods type and GTIN.
6. **Byte-level output changes for every UAE document**: a new UUID, line AED amounts, gross price and so on.
   Re-run your ASP's sandbox tests.
7. Free-trade-zone (flag position 1) and disclosed-agent billing (position 6) need data the generator
   does not produce yet. They are refused with EIH-AE-064 rather than sent to fail.

No data is migrated or deleted. The new profile field is added by `bench migrate`.

## 6. Rollback

1. `bench --site <site> backup` (before upgrading, as always).
2. Check out 0.3.0 (`git checkout 83e9759` in `apps/thinknxg_einvoice_hub`) and run `bench --site <site> migrate`.
   The *Legal Registration Authority* column stays in the database and is ignored by 0.3.0; no data is lost.
3. Transactions already generated with 0.3.1 keep their stored XML and UUID. Re-processing them under
   0.3.0 regenerates the pre-0.3.1 layout, which the official rules reject.

## 7. How to reproduce

```bash
# unit tests (no bench); add the official resources and UBL XSDs to run the official checks
AE_PINT_RESOURCES=/opt/pint-ae-resources-1.0.5/billing AE_PINT_SB_RESOURCES=/opt/pint-ae-resources-1.0.5/sb \
UBL21_XSD_DIR=/opt/ubl21 CCTS_XSD=/opt/ccts/CCTS_CCT_SchemaModule.xsd \
python -m unittest thinknxg_einvoice_hub.tests.test_uae

# bench pipeline
bench --site <site> execute thinknxg_einvoice_hub.tests.bench_uae.run \
    --kwargs "{'resources': '/opt/pint-ae-resources-1.0.5'}"
```

The official resources come from OpenPeppol: https://docs.peppol.eu/poac/ae/pint-ae/ (download `resources.zip`).
