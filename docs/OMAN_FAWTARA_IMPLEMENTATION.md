# Oman Fawtara: Implementation

Oman is a separate compliance engine (`om_pint_om`) next to the UAE engine (`uae_pint_ae`). Both use the
canonical invoice model, the processing pipeline, the ASP adapter layer and the lifecycle tracking; neither
uses the other's rules. Official requirements and sources: `OMAN_FAWTARA_SPECIFICATION.md`.

## Where the hub sits

```
 ERP (C1 data) ──> thinkNXG E-Invoice Hub ──> Oman accredited provider (C2) ──Peppol──> buyer's provider (C3) ──> buyer (C4)
                    canonical model              validates, transmits,          │
                    Oman engine (PINT OM)        builds the Tax Data Document   └──TDD──> OTA access point (C5) ──> OTA (C6)
                    lifecycle tracking  <── MLS (invoice) from C3, MLS (TDD) from C5, relayed by C2
```

The hub acts for the seller (C1). It prepares and validates the PINT OM invoice, computes the identifiers C1 is
responsible for (Seller UUID, QR) and the Invoice UUID C2 will recompute, submits through a provider adapter and
records the outcomes. It does not transmit over Peppol, build the TDD or talk to the OTA.

## Code

```
compliance/
  base.py                  country engine interface (BaseComplianceEngine)
  registry.py              built-in engines + einvoice_hub_compliance_engines hook
  uae/                     PINT AE (unchanged in behaviour)
  oman/
    constants.py           identifiers, code lists, UUID namespace, substitute participant IDs, QR constants
    identifiers.py         VATIN, 0248 participant ID, Invoice UUID (BTOM-002), Seller UUID (BTOM-004)
    transaction_types.py   BTOM-001 20-position bitmap
    tax_rules.py           S / Z / E / O, effective-dated rates, reason codes
    validator.py           EIH-OM-* pre-submission rules (see OMAN_FAWTARA_VALIDATION.md)
    ubl_generator.py       canonical -> PINT OM UBL Invoice / CreditNote, and inbound parsing
    schematron.py          optional run of the official PINT OM Schematron (Saxon)
    qr.py                  QR TLV / Base64 payload
    status_mapper.py       provider MLS codes -> reporting and delivery statuses
    pint_om.py             the engine class
api/oman.py                Oman API (OMAN_FAWTARA_API.md)
tests/test_oman.py         framework-independent tests, UAE goldens
tests/bench_oman.py        bench integration checks against the mock provider
tests/mock_oman_provider.py, tests/oman_fixtures.py
samples/oman/              sample inputs, canonical invoices, XML, validation results (test fixtures)
```

## Canonical model additions (all optional, schema stays 1.0)

| Canonical field | Oman term |
| --- | --- |
| `document.issue_time` | IBT-168 issue time |
| `document.uuid` | BTOM-002; computed by the engine when empty |
| `document.transaction_type_flags` or `extensions.om.transaction_types` | BTOM-001 |
| `document.period_start` / `period_end` | invoicing period (summary, continuous supply) |
| `supplier.uuid` | BTOM-004 Seller UUID; computed for B2C and profit-margin invoices |
| `party.identifier`, `party.identifier_scheme` | IBT-029/046 with CL-06-OM scheme |
| `address.address_line`, `address.subdivision` (CL-13-OM code) | IBT-162/163, country subdivision |
| `references.original_invoice_uuid`, `credit_reason_code` | BTOM-031, BTOM-032 |
| `references.prepayment_number`, `prepayment_uuid` | BTOM-027, BTOM-014 |
| `line.item_type` (G/S), `service_type`, `commodity_code` (HS), `industry_code` (ISIC), `origin_country`, `profit_margin_code` | BTOM-019, BTOM-034, IBT-158, BTOM-033, IBT-159, BTOM-025 |
| `delivery.incoterms`, `customs_declaration`, `import_date` | BTOM-022, BTOM-021, BTOM-030 |
| `extensions.om.b2c`, `extensions.om.substitute_participant`, `extensions.om.pm_total` | B2C buyer, substitute participant ID, BTOM-020 |
| `extensions.om.qr_base64` (output) | QR payload for the printed invoice |

Money: the normaliser rounds amounts to the currency's minor unit (3 decimals for OMR; still 2 for AED), so UAE
amounts are unchanged. The Oman generator writes line amounts with 3 decimals and document totals with 2, as the
official rules require.

## Outbound flow

ERP invoice -> canonical (connector / mapping) -> seller filled from the Company Integration Profile -> credit notes:
original UUID and date added from the hub's own records -> engine enrichment (0248 addresses, substitute participant,
transaction type, Seller UUID, QR) -> hub validation -> PINT OM XML with Invoice UUID -> official Schematron (if
installed) -> provider adapter -> provider result -> MLS codes translated -> lifecycle fields -> ERP status sync
(including the Invoice UUID when `uuid_field` is configured on the ERPNext connection).

## Inbound flow

Provider delivers a PINT OM document (signed webhook, inbound API or polling) -> engine chosen by the document's
CustomizationID when a tenant has companies in several countries -> parsed to canonical -> buyer company resolved by
VATIN -> validated -> draft purchase invoice in the ERP (ERPNext connector).

## Lifecycle for Oman

| Field | Oman meaning |
| --- | --- |
| Internal Validation | hub rules, and the official Schematron when installed |
| ASP Submission | accepted / rejected by the accredited provider (C2) |
| Tax Authority Reporting (`fta_status`) | TDD MLS from C5: AP/AB -> Reported, RE -> Rejected |
| Peppol Delivery | invoice MLS from C3: AP/AB -> Delivered, RE -> Failed; Not Applicable for B2C, export and other substitute receivers |
| ERP Synchronisation | status written back to the ERP |

New overall status **Reported**: final state when no Peppol delivery is expected (B2C, export) and the TDD was
accepted. Provider acceptance alone never sets reporting or delivery.

## Enabling an authorised Oman integration

1. Choose an OTA-accredited service provider and obtain its API documentation and sandbox credentials.
2. Agree the C1-C2 format: PINT OM UBL (this engine's output) or the provider's JSON (canonical JSON + REST mapping).
3. Create an ASP REST API Configuration for the provider (ASP_GUIDE.md) and map its MLS / status fields to
   `invoice_mls_code` and `tdd_mls_code` (or `fta_status` / `delivery_status`).
4. Install the official PINT OM resources and set `official_validation: required` (OMAN_FAWTARA_CONFIGURATION.md).
5. Configure the Oman company profiles (VATIN, CR, three address lines, subdivision code, telephone) and the ERP
   item fields (goods/services, HS, ISIC, service type).
6. Run the sandbox test plan in OMAN_FAWTARA_TESTING.md against the provider's sandbox; record the results.
7. Only after the provider confirms acceptance in its sandbox, and the taxpayer is registered on the Fawtara Portal and
   Oman SMP, switch the ASP Connection to Production.

Developing this connector is not approval to transmit production invoices; that depends on the OTA roll-out, the
provider's accreditation and the taxpayer's onboarding.
