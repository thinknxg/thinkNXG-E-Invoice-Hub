# Oman Fawtara: Validation

Validation runs in three layers. A document is submitted only when none reports an error.

| Layer | When | Rules | Authority |
| --- | --- | --- | --- |
| 1. Canonical structure | after normalisation | `canonical/invoice_schema.py` (HUB-*) | hub |
| 2. Hub Oman rules | before the XML is built | `compliance/oman/validator.py`, `tax_rules.py` (EIH-OM-*) | hub; each rule cites the official rule it mirrors |
| 3. Official PINT OM Schematron | on the generated XML | OpenPeppol PINT OM 1.0.1, official rule IDs | official artefacts, run by the hub when installed |

The accredited service provider validates again before transmission; its result is authoritative.

Layer 2 exists so that the ERP gets a canonical field path (for example `lines[0].industry_code`) instead of an
XPath. Layer 3 adds what only the official artefacts know: HS and ISIC code-list membership, every rule's exact
arithmetic and every combination the hub rules do not repeat. With `official_validation: required` a document
cannot leave the hub unless layer 3 ran and passed. Results are stored on the transaction (Validation Messages)
and returned by the API.

## Hub rules (EIH-OM-*)

| Rule | Field | Checks | Official rule(s) mirrored |
| --- | --- | --- | --- |
| 001 | document type / kind | 380, 381, 389, 261 tax documents only | UNCL1001 subset |
| 002 | invoice number | present | IBT-001 |
| 003 | invoice date | present, not in the future (Muscat time) | IBR-171-OM |
| 004 | issue time | present, `hh:mm:ss` | ALIGNED-IBRP-016-OM |
| 005 | currency | ISO 4217 | IBT-005 |
| 006 | exchange rate | required for non-OMR, max 7 decimals | IBR-004/005-OM |
| 007 | invoice UUID | v5 when supplied | IBR-002-OM |
| 008 | transaction type | 20 x 0/1, exactly one of full / simplified, known names | IBR-001/043-OM, CL-03-OM |
| 009 | transaction type | forbidden combinations; self-billing documents need the self-billed type | IBR-138..152/176/177-OM |
| 010-012 | parties | legal names; country; address lines 1-3, city, postcode | IBR-010/019-OM |
| 014 | subdivision | CL-13-OM code | CL-13-OM |
| 015-016 | VATIN | required by type; `OM` + 10 digits | IBR-006/017-OM |
| 017 | seller telephone | required | IBR-011-OM |
| 018 | Seller UUID | v5; required for B2C | IBR-173-OM |
| 019 | identifiers | CL-06-OM scheme; seller identifier for import / special zone; ICID for import of goods | IBR-007/153-OM, CL-06-OM |
| 020 | seller address | electronic address present | IBT-034 |
| 021 | buyer | VATIN or identifier by type | IBR-016-OM |
| 022 | countries | buyer OM for self-billed / import; seller OM for PM self-invoice; seller not OM for import of services | IBR-020/087/160-OM |
| 023 (warning) | buyer address | empty electronic address | OM SRA 10.3.1 |
| 030-032 | credit notes | reason code (CL-02-OM), preceding number, date and v5 UUID | IBR-023/032/175-OM |
| 033 | periods | summary / continuous supply period, same month | IBR-036/037-OM |
| 034 | prepayment | number and UUID when a prepaid amount exists | IBR-058-OM |
| 035-036 | delivery | export country, e-commerce address, import customs data, Incoterms | IBR-014/040/085-OM, CL-09-OM |
| 037 | profit margin | total amount due | IBR-082-OM |
| 040-047 | tax category | S/Z/E/O only; 5% for S on the date; zero VAT for Z/E/O; reason codes for E and Z, none for S and O | CL-04/05/10-OM, ALIGNED-IBRP-S-05/S-10-OM, IBR-069/070/077-OM |
| 048 | breakdown | one breakdown per E / Z / O category | ALIGNED-IBRP-E/O/Z-01-OM |
| 050-052 | lines | at least one; item name; goods/services flag | IBR-078-OM, CL-07-OM |
| 053 | HS code | goods need one; exactly 12 digits | IBR-079/080/174-OM |
| 054 | ISIC code | required except simplified / import / PM self-invoice; 6 digits | IBR-081-OM |
| 055 | service type | CL-12-OM; export of services needs a service line | CL-12-OM, IBR-155-OM |
| 056-058 | special types | origin country for imports; PM reason codes; O category for PM self-invoice | IBR-084/086-OM, CL-11-OM |
| 059 | amounts | not negative (credit notes carry positive values) | IBR-137-OM |
| 060 | line VAT | net x rate within 0.001 | IBR-168-OM |
| 061 | line periods | same month for summary invoices | IBR-057-OM |
| 070 | S breakdown | equals line VAT + charge VAT - allowance VAT | ALIGNED-IBRP-S-09-OM |
| 071-074 | totals | non-negative, max 3 decimals, VAT total and total with VAT consistent | IBR-137-OM, IBR-DEC-03-OM, ibr-co-14/15 |
| 090 | official check | warning (or error with `required`) when the official Schematron did not run | - |

## Decimals

Line amounts and line VAT: up to 3 decimals (baisa). Document totals, VAT breakdown and `TaxTotal`: at most 2
decimals, each rounded once from the 3-decimal line sums, which is what the official rules (ibr-091, ibr-123..125,
ibr-co-10/14/15, ALIGNED-IBRP-S-08/S-09-OM) and the official "baisa gap" examples require.

## Results on the test fixtures

All valid fixtures (standard, zero-rated, exempt, credit note, USD, B2C, export, self-billing, allowances / charges)
return **zero errors and zero warnings** from the official PINT OM 1.0.1 Schematron and validate against the OASIS
UBL 2.1 XSD. This shows the documents conform to the published rules; it is not acceptance by an accredited
provider or the OTA.
