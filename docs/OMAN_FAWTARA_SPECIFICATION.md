# Oman Fawtara: Regulatory and Technical Specification

Research date: 2026-11-20. This document records what the hub implements for Oman and the official
source for each requirement. It is an engineering record, not legal or tax advice. Confirm current
requirements with the Oman Tax Authority (OTA) and your accredited service provider before go-live.

## 1. Sources

| Ref | Document | Status / date | Where |
| --- | --- | --- | --- |
| [PINT-OM] | OpenPeppol **PINT OM Billing** v1.0.1 and **PINT OM Self-Billing** v1.0.1: semantic model, syntax binding, code lists, rules, Schematron. Ruleset version 1.0.1, "Authority: Tax Authority Oman" | Published in PDK 1.4.4, 2026-07-29 | https://docs.peppol.eu/poac/om/pint-om/ (`resources.zip`) |
| [OM-SRA] | OpenPeppol **Oman - Solution Reference Architecture** | Final v1.0.3, 2026-07-27 | Published by OpenPeppol; copy used from github.com/phax/peppol-om (`docs/`) |
| [OM-TDD] | Peppol OM Tax Data Document 1.0.1 (Schematron, XSD) | 2026-07-23 | github.com/phax/peppol-om (`docs/om-tdd-resources-1.0.1-*.zip`) |
| [DEC-189] | OTA Decision No. 189/2026 amending the VAT Executive Regulations (mandatory e-invoicing) | Issued 2026-08-09 | Reported by KPMG (2026-08-13), Sovos (2026-08-13), Alvarez & Marsal (2026-08-25) |
| [VAT-LAW] | Oman VAT Law, Royal Decree 121/2020 | In force 2021-04-16 | taxoman.gov.om |

The official PINT OM 1.0.1 resources were obtained from github.com/phax/phive-rules (`docs/PINT OM/pint-om-resources-1.0.1.zip`,
`pint-om-sb-resources-1.0.1.zip`), because docs.peppol.eu could not be downloaded from the build environment. The examples
in those bundles validate with zero errors under their own Schematron, which confirms the bundle is internally consistent;
operators should still download `resources.zip` from docs.peppol.eu themselves (see OMAN_FAWTARA_CONFIGURATION.md).

## 2. Architecture and roll-out

* **Model**: decentralised 5/6-corner Peppol model with a central Oman SMP, run by the OTA as Peppol Authority [OM-SRA 1.2].
  Seller (C1) -> seller's accredited provider (C2) -> buyer's provider (C3) -> buyer (C4); C2 and C3 each send a
  Tax Data Document (TDD) to the Tax Authority's access point (C5), which delivers it to the OTA (C6) [OM-SRA 2.2].
* **C1 -> C2 format is bilateral** ("C1-C2 bilateral data submission format, outside Peppol") [OM-SRA 3.2 step 2.d.iii].
  The hub (acting for C1) produces the PINT OM UBL invoice, which C2 then validates and transmits; a provider may instead
  accept its own format, which the hub supports through the REST configuration engine.
* **Accreditation**: providers must be accredited by the OTA through the Fawtara Portal; taxpayers link to a provider on
  the portal; the provider registers them on the Oman SMP within 3 working days [OM-SRA 3.1-3.4].
* **Roll-out** [DEC-189]: mandatory from **1 April 2027** for taxable persons with annual supplies above OMR 5 million and
  from **1 October 2027** for all other taxable persons; a pilot phase with selected large taxpayers began in August 2026.
  Earlier announcements (phases in February and August 2027) were replaced by the decision. Sovos reported the decision as
  pending Gazette publication on 2026-08-13; confirm the current dates with the OTA.

## 3. Requirement table

Status: **Implemented** = in code and tested; **Provider** = performed by the accredited service provider, tracked by
the hub; **Configurable** = implemented with values that can be changed without code; **Open** = not available or not
verified, see section 4.

| Requirement | Official source | Technical requirement | Implementation status |
| --- | --- | --- | --- |
| Invoice structure | [PINT-OM] syntax binding, examples | UBL 2.1 Invoice / CreditNote; `CustomizationID` `urn:peppol:pint:billing-1@om-1` (self-billing `...selfbilling-1@om-1`), `ProfileID` `urn:peppol:bis:billing` / `...selfbilling` | Implemented (`ubl_generator.py`); output passes the official 1.0.1 Schematron and the OASIS UBL 2.1 XSD |
| Document types | [PINT-OM] UNCL1001 subset, [OM-SRA 10.2.1] | 380 invoice, 381 credit note, 389 self-billed invoice, 261 self-billed credit note; 383 debit note appears in the rules | Implemented for 380/381/389/261. **Open**: 383 debit note (no canonical debit-note type yet) |
| Transaction type (BTOM-001) | [PINT-OM] CL-03-OM, IBR-001/043-OM, IBR-138..152/176/177-OM | 20-character bitmap on `InvoiceTypeCode/@name`; position 1 full or 2 simplified, never both; incompatible combinations rejected | Implemented (`transaction_types.py`, validator EIH-OM-008/009) |
| Invoice UUID (BTOM-002) | [OM-SRA 10.2.3], IBR-002-OM | UUID v5, namespace `e0bc4ac8-b025-46e5-a76d-0c893fc3027e`, name = `scheme sellerEndpoint typeCode number date taxTotal totalWithTax [BTOM-020]` as written in the document | Implemented and tested; the hub computes the same value C2 must compute (verified by a mock provider that recomputes it) |
| Invoice numbering | [PINT-OM] IBT-001, [OM-SRA 4.2] | Unique sequential number issued by the seller | Taken from the ERP; the hub rejects duplicates per company (Duplicate status). Sequence gaps are the ERP's responsibility |
| Dates and times | [PINT-OM] IBT-002, IBT-168, ALIGNED-IBRP-016-OM, IBR-171-OM | `YYYY-MM-DD`; issue time `hh:mm:ss` mandatory; issue date not in the future (Asia/Muscat) | Implemented (EIH-OM-003/004); ERPNext posting time mapped to issue time |
| Currency | [PINT-OM] IBR-004/005/034/059/065/066/136/172-OM | Tax currency OMR; non-OMR invoices carry `TaxCurrencyCode`, `TaxExchangeRate` (max 7 decimals) and VAT restated in OMR | Implemented. See section 4 for the 1.0.1 rule conflict on S-rated foreign-currency invoices |
| Decimal precision | [PINT-OM] IBR-DEC-03-OM, ibr-091, ibr-123..125, ALIGNED-IBRP-S-08/S-09-OM, examples P1-P4 | Line amounts and line VAT up to 3 decimals (baisa); document totals and VAT breakdown at most 2 decimals, rounded once from line sums | Implemented (`document_amount_decimals`, default 2) |
| Supplier identifiers | [OM-SRA 10.3.1], IBR-006/007/010/011-OM, CL-06-OM, CL-13-OM | VATIN `OM` + 10 digits; Peppol address `0248:<VATIN>`; party identifier scheme CR/TIN/CID/PASNUM/OTHID/ICID/SZLN; address lines 1-3, city, postcode; subdivision code; telephone | Implemented (company profile fields, validator EIH-OM-012/015-020) |
| Buyer identifiers | IBR-016/017/019/020/153-OM, [OM-SRA 10.3.1] | Buyer VATIN or identifier by transaction type; substitute participant IDs 997770000095..099 for receivers outside Peppol | Implemented; `extensions.om.b2c` and `extensions.om.substitute_participant` select the substitute ID |
| B2C | [OM-SRA 4.1-4.3], IBR-173-OM | Simplified invoice; buyer `General customer` / OM / `0248:997770000099`; Seller UUID mandatory | Implemented (`extensions.om.b2c`) |
| Seller UUID (BTOM-004) and QR | [OM-SRA 4.2, App. D] | UUID v5 of `1.1|01|number|seller|VATIN|date|time|total|VAT` upper-cased (profit margin: type 02, total due); QR = Base64 TLV, max 700 chars | Implemented (`identifiers.py`, `qr.py`) and checked against the official example; QR image rendering is left to the ERP print format |
| Tax categories | [PINT-OM] CL-04-OM, ALIGNED-IBRP-*-OM, IBR-061/067/069/070/077-OM | S (5%), Z (0%, reason VATZR-OM-01..16), E (no rate, reason VATEX-OM-01..12), O (no rate, no reason) | Implemented (`tax_rules.py`); rates effective-dated and configurable (Compliance Tax Rule) |
| VAT rate | [VAT-LAW], ALIGNED-IBRP-S-05-OM | Standard rate 5% | Configurable (`standard_rate_schedule`); ruleset 1.0.1 accepts only 5 for S |
| Line VAT | IBR-168-OM, IBR-158-OM | Line VAT = net x rate (0.001 tolerance); line amount incl. VAT in `ItemPriceExtension` | Implemented (EIH-OM-060) |
| Item classification | IBR-078..081-OM, IBR-174-OM, CL-07/08/12-OM | Goods/services flag per line; 12-digit Oman HS code for goods; 6-digit ISIC per line (except simplified/import); service type code for services | Implemented (format checks in the hub; list membership by the official Schematron) |
| Credit notes | IBR-023/032-OM, CL-02-OM | Reason code CAN/VAT/VAL/QTY/OTH; preceding invoice number, date and UUID | Implemented; the hub fills the original UUID and date from its own records when the ERP sends only the number |
| Invoice cancellation | [OM-SRA 8] | No separate cancellation message in Peppol. A supply is reversed by a credit note (reason CAN); TDD replacement (Resubmit / Disregard) is handled by C2/C3 | Credit note implemented; hub "Cancel" is an internal status only. TDD handling: **Provider** |
| Self-billing, third party, summary, continuous supply, export, import, profit margin, e-commerce, special zone, prepayment | [PINT-OM] rule set, [OM-SRA 9] | Type-specific mandatory data (periods, delivery country, customs data, PM total, prepayment references ...) | Self-billing, export, B2C tested end to end; other types: validator rules and XML elements implemented, not covered by official-Schematron fixtures yet |
| XML format and schema | [PINT-OM], OASIS UBL 2.1 | UBL 2.1 namespaces, UTF-8, element order | Implemented; UBL 2.1 XSD validation passes for all fixtures |
| Business-rule validation | [PINT-OM] Schematron 1.0.1 | Official Schematron (shared PINT rules + OM jurisdiction rules) | Hub pre-checks (EIH-OM-*), plus the official Schematron in the pipeline when installed (`official_validation`) |
| Digital signature / certificates | [OM-SRA 11, 12] | No document-level signature in PINT OM. Transport security is the Peppol PKI (AS4, access point certificates) between C2, C3 and C5 | Not applicable to the hub; **Provider** |
| Transmission | [OM-SRA 2, 11] | Peppol AS4 with SBDH (`MLS_TYPE` `ALWAYS_SEND`, `COUNTRY_C1`) between access points | **Provider** |
| Tax Data Document and reporting | [OM-SRA 2.2, 5.4, 10.2.2], [OM-TDD] | C2/C3 build the TDD (`urn:peppol:taxdata:om-1`) and send it to C5 within the SLA | **Provider**; the hub tracks the outcome as tax-authority reporting status |
| Acknowledgements and statuses | [OM-SRA 2.3, 8] | MLS codes AP / AB / RE from C3 (invoice) and C5 (TDD) | Implemented: `invoice_mls_code` -> Peppol delivery status, `tdd_mls_code` -> tax-authority reporting status (`status_mapper.py`) |
| Access point / provider requirements | [OM-SRA 3, 5] | OTA accreditation, SMP registration of the taxpayer, MLS handling | **Provider**. No accredited provider is integrated yet (section 4) |
| B2B, B2G, B2C scope | [OM-SRA 4, 9, App. C] | Domestic B2B, B2C (TDD only), export, import, self-billing, third party, profit margin; G2B / B2G follow B2B timings | B2B and B2C implemented; B2G uses the B2B flow |
| Retention | [OM-SRA App. C.1] | Provider retention per the Oman PASR | Hub keeps immutable payloads indefinitely; PASR **Open** |

## 4. Open items (not available to this project, or not verified)

1. **Accredited provider API (C1 -> C2)**: no Oman provider's API documentation was available. Submission is implemented
   through the generic adapter contract and the configurable REST engine, tested only against a mock provider.
2. **Oman PASR** (Peppol Authority Specific Requirements: production SLAs, retention) and the **OTA data dictionary**:
   referenced by [OM-SRA] but not obtained.
3. **Foreign-currency invoices with standard-rated lines** (ruleset 1.0.1): IBR-066-OM requires an S breakdown in OMR
   while ALIGNED-IBRP-S-01-OM allows only one S breakdown per document. The hub puts the breakdown in the OMR `TaxTotal`
   and only the total in the document-currency `TaxTotal`, the one layout that passes both rules. Confirm with the provider.
4. **QR amounts**: the official Seller UUID example uses 3-decimal amounts (302.340). The hub uses 3 decimals for OMR in
   the QR / Seller UUID while the XML totals carry 2 decimals; no rule cross-checks them. Confirm with the provider.
5. **Invoice UUID example**: [OM-SRA 10.2.3] prints `b3fc2859-...` for its example input; the stated method gives
   `7b95376b-e63c-50e0-a0e9-62f2092288a6`, as also recorded in phax/peppol-om. The hub follows the method.
6. **Debit notes (383)** are not supported by the canonical model.
7. **Code-list updates**: HS and ISIC lists live in the official resources; install new resources when OpenPeppol
   publishes a new PINT OM release and update `constants.py` if code lists change.
