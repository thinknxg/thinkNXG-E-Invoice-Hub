# Oman Fawtara: Audit and Final Implementation Gap Report

Audit date 2026-11-20, baseline v0.2.0 (commit `f219875`, 40 passing framework-independent tests). Final status
for release 0.3.0. Requirements and sources: `OMAN_FAWTARA_SPECIFICATION.md`.

## 1. Baseline audit (v0.2.0)

| Area | Found | Reused for Oman |
| --- | --- | --- |
| Country engines | `BaseComplianceEngine`, registry with `einvoice_hub_compliance_engines` hook, one engine `uae_pint_ae` | Yes: Oman is a second engine; no UAE code changed |
| Canonical model | country-neutral JSON v1.0 with `extensions` | Yes: optional Oman fields, schema version unchanged |
| UBL | shared writer / safe parser (`compliance/shared/xml.py`), UAE generator | Shared writer reused; separate Oman generator |
| Tax | canonical categories, UAE code mapping | Oman `tax_rules.py`, effective-dated |
| Validation | canonical structure (HUB-*), UAE rules (EIH-AE-*) | Oman rules (EIH-OM-*) + optional official Schematron |
| ASP layer | capability-based adapter contract, REST configuration engine (10 auth types), sandbox adapter, UAE adapters | Reused; MLS fields added to the REST mapping |
| Lifecycle | five independent status fields, lock, idempotency, retry, reconciliation, duplicates | Reused; "Reported" final state added for no-delivery flows |
| Tenancy / security | tenant-scoped records, permission queries, Password fields, masked logs, signed webhooks, SSRF guard | Reused unchanged |
| Jobs | processing queue, retry, status sync, inbound polling, log purge | Reused unchanged |

Gaps found in the uncommitted, interrupted first Oman attempt and corrected: the Invoice UUID used a private
namespace and field string instead of the OTA method; the Seller UUID was modelled as a per-company setting (it is
per invoice); goods/services type, subdivision code and line VAT were in the wrong UBL elements; the ISIC code, three
address lines, telephone and issue time were not required; exempt categories carried a rate; documents failed the
official rules on decimals. None of that code had been committed.

## 2. Gaps closed in 0.3.0

| # | Gap | Resolution |
| --- | --- | --- |
| G1 | No Oman engine | `compliance/oman/`, engine `om_pint_om`, Compliance Profile created on install / migrate |
| G2 | No verified Oman specification | PINT OM 1.0.1 and OM SRA 1.0.3 studied; requirement table with sources |
| G3 | Identifiers | 0248 participant IDs, substitute participants, Invoice UUID and Seller UUID by the published method, QR payload |
| G4 | Tax | S / Z / E / O with official reason codes; effective-dated, configurable rates (Compliance Tax Rule) |
| G5 | Document | PINT OM Invoice / CreditNote / self-billing; baisa decimals; foreign currency; B2C; export |
| G6 | Validation | 57 hub rule checks mapped to official rules; official Schematron in the pipeline when installed |
| G7 | Status | MLS (invoice / TDD) -> delivery / reporting statuses; "Reported" for B2C / export |
| G8 | ERP | ERPNext: issue time, item fields (HS, ISIC, G/S), credit reason, B2C flag, reason codes, address line 3 |
| G9 | Credit notes | original invoice UUID and date filled from hub records |
| G10 | Inbound | PINT OM parsing; multi-country tenants route by CustomizationID (bug fixed for mixed tenants) |
| G11 | API / dashboard | `api/oman.py`; dashboard country / status filters and Oman counts from real data |
| G12 | Migration | patch `v0_3.country_code_backfill`; UAE data preserved (tested) |
| G13 | Tests / samples / docs | 38 new unit tests, 28 bench checks, samples, 7 new documents |

## 3. Remaining gaps and external dependencies

| # | Item | Owner | Effect |
| --- | --- | --- | --- |
| R1 | No accredited Oman provider integrated; provider API (C1 -> C2 format, auth, status fields) unknown | Kreatao + chosen provider | Submission tested only against a mock provider |
| R2 | OTA sandbox / provider sandbox testing | provider | Required before "Sandbox Tested" |
| R3 | Oman PASR and OTA data dictionary not obtained | OTA / OpenPeppol | SLAs, retention and any extra national fields unconfirmed |
| R4 | Foreign-currency S-rated layout (ruleset 1.0.1 rule conflict) | confirm with provider | Hub uses the one layout that passes both rules |
| R5 | QR / Seller UUID amount formatting (3 vs 2 decimals) | confirm with provider | No official rule cross-checks it |
| R6 | Debit note (383) | product | Not in the canonical model |
| R7 | Summary, continuous supply, import, profit margin, e-commerce, special zone, prepayment | product | Rules and XML implemented; not yet covered by official-Schematron fixtures |
| R8 | Official resources not bundled (licence and update cycle) | operator | Install per OMAN_FAWTARA_CONFIGURATION.md |
| R9 | **UAE (pre-existing):** UAE output fails the official PINT AE Schematron (2026.3 / 2026.5 / 2026.11), for example BTAE-07 unique identifier and BTAE-10 AED line amounts missing | product | UAE is not "awaiting validation only"; needs its own fix release. Not changed here by design |
| R10 | Screens not tested in a browser | QA | Dashboard / forms checked by code review and API only |

## 4. Feature matrix

"Officially validated" means checked with official validation artefacts (OpenPeppol PINT OM 1.0.1 Schematron,
OASIS UBL 2.1 XSD). It does **not** mean acceptance by an accredited provider or the OTA: none has taken place.

| Feature | Implemented | Unit tested | Integration tested | Officially validated |
| --- | --- | --- | --- | --- |
| Oman country profile | Yes | Yes | Yes (bench, install + migrate) | Not applicable |
| Invoice mapping | Yes | Yes | Yes (mock provider) | PINT OM 1.0.1 Schematron + UBL XSD: pass on all fixtures; provider / OTA: **No** |
| Credit notes | Yes | Yes | Yes | Schematron + XSD: pass; provider / OTA: **No** |
| Tax calculations | Yes (S, Z, E, O) | Yes | Yes | Schematron: pass for S, Z, E (O by unit tests only); provider / OTA: **No** |
| Document generation | Yes | Yes | Yes | Schematron + XSD: pass; provider / OTA: **No** |
| XML / schema validation | Yes (hub rules + official Schematron hook) | Yes | Yes (Schematron in pipeline) | Uses the official artefacts |
| Provider submission | Yes (adapter contract, REST engine) | Yes | Mock provider only | **No** (R1, R2) |
| Reporting workflow (TDD status) | Status tracking only; TDD is the provider's | Yes | Mock MLS only | **No** |
| Inbound invoices | Yes | Yes | Yes (mock provider, multi-country tenant) | **No** |
| Status synchronization | Yes (MLS mapping, polling, ERP sync) | Yes | Yes (mock) | **No** |

## 5. Production readiness

Not production-ready for Oman until R1-R3 are closed: a real accredited provider integration tested in its sandbox,
the taxpayer onboarded on the Fawtara Portal and Oman SMP, and the OTA roll-out phase reached (1 April 2027 for
supplies above OMR 5 million, 1 October 2027 for others, per Decision No. 189/2026).
