# Oman Fawtara: Testing

## Framework-independent tests (no bench)

```bash
python -m unittest discover -s thinknxg_einvoice_hub/tests -t .
python -m unittest thinknxg_einvoice_hub.asp_connectors.uae.microvista.tests.test_microvista
```

Optional official checks (skipped unless configured):

```bash
pip install saxonche xmlschema
export OM_PINT_RESOURCES=/opt/pint-om-resources-1.0.1/billing      # official PINT OM Billing resources
export OM_PINT_SB_RESOURCES=/opt/pint-om-resources-1.0.1/sb        # official Self-Billing resources
export UBL21_XSD_DIR=/path/to/ubl21                                # OASIS UBL 2.1 xsd (maindoc/, common/)
export CCTS_XSD=/path/to/CCTS_CCT_SchemaModule.xsd
python -m unittest discover -s thinknxg_einvoice_hub/tests -t .
```

`tests/test_oman.py` covers: Invoice UUID and Seller UUID against the published examples, QR TLV bytes against the
official table, transaction types, tax rules and effective-dated rates, MLS status mapping (including REST response
mapping), normalisation to baisa, supplier / buyer / line / decimal mapping, every scenario's Invoice UUID recomputed
the way a provider must, credit notes, zero-rated / exempt, foreign currency, B2C, export, self-billing,
allowances / charges, parse round trip, DTD refusal, every validation rule family, ERPNext Oman options, and the
**UAE regression goldens** (UAE XML must stay byte-identical to v0.2.0).

## Bench integration checks

```bash
bench --site <site> execute thinknxg_einvoice_hub.tests.bench_oman.run \
  --kwargs "{'resources': '/opt/pint-om-resources-1.0.1'}"
```

Runs the real pipeline against the mock Oman provider in a dedicated tenant (OMTEST): standard invoice (four
outcomes), credit note with the original UUID filled from hub records, B2C ending as Reported, TDD rejection, buyer's
provider rejection, late MLS completed by a status poll, retry after a temporary failure, duplicate detection, hub
validation failure, official Schematron failure inside the pipeline, inbound PINT OM, multi-country inbound routing
(UAE and Oman documents in one tenant), dashboard counts, the Oman API, and a UAE sandbox flow on the same site.

## Results (2026-11-20, Frappe 16.56.0)

| Suite | Result |
| --- | --- |
| Framework-independent tests, with official Schematron and UBL XSD enabled | 78 passed (40 existing + 38 new) |
| Microvista adapter tests | passed |
| UAE output vs v0.2.0 (5 documents: invoice, sample, credit note, USD, mixed categories) | byte-identical XML, validation messages and canonical JSON |
| Bench checks on a migrated v0.2.0 site with UAE data (`hub.localhost`) | 28 / 28 |
| Bench checks on a fresh install (`fresh-om.localhost`) | 27 / 27 (no UAE company there) |
| Migration of the v0.2.0 site | 8 UAE transactions, 26 payloads, validation messages unchanged; `country_code` set to AE |
| Official PINT OM 1.0.1 Schematron on all generated fixtures | 0 errors, 0 warnings |
| OASIS UBL 2.1 XSD on all generated Oman documents and UAE goldens | valid |

Not tested: any real accredited provider, the OTA sandbox, the Fawtara portal, the screens in a browser.

## Sandbox test plan for a real provider

1. Standard B2B invoice; credit note referencing it (reason CAN).
2. Zero-rated, exempt, out-of-scope and mixed-category invoices.
3. B2C simplified invoice (check the provider accepts the hub's Seller UUID and QR values).
4. Export invoice; self-billing invoice; foreign-currency invoice with standard-rated lines (open item 3 in the
   specification).
5. Rejections: invalid VATIN, wrong VAT, missing ISIC; confirm the provider's error codes reach the transaction.
6. MLS: confirm the provider reports invoice MLS and TDD MLS, and map them to `invoice_mls_code` / `tdd_mls_code`.
7. Inbound: receive an invoice addressed to the company and confirm the draft purchase invoice in the ERP.
Record the provider's validation results; only then mark the provider "Sandbox Tested".
