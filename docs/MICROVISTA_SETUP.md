# Microvista setup

| | |
| --- | --- |
| Legal name | Microvista Technologies LLC |
| Accreditation number | 157529 (Ministry of Finance directory, page dated 11/11/2026) |
| Website | https://www.microvistatech.com/e-invoicing-in-uae |
| Onboarding contact (from the directory) | uaesales@microvistatech.com |
| Integration status | Skeleton - Pending API Documentation |
| Production ready | No |

## What exists

* Adapter `microvista` (`asp_connectors/uae/microvista/`), selectable on any ASP Connection and in
  the directory, without any change on the ERP side.
* **Microvista Settings**: one record per tenant company; creates and maintains the ASP Connection,
  shows a readiness report and the checklist below, offers Verify Credentials.
* The adapter contains no Microvista endpoint, field name or signature scheme. It runs the contract
  entered in an ASP REST API Configuration and refuses to transmit until the required parts exist.

## What is missing

No public API documentation was found on 2026-11-12 (the provider's site and a web search were
checked). Request the API reference and sandbox credentials from Microvista, then fill in:

| ID | Needed from Microvista | Where it goes |
| --- | --- | --- |
| MV-01 | Sandbox and production base URLs | Configuration > Base URLs |
| MV-02 | Authentication scheme, credential names, token endpoint and lifetime | Authentication |
| MV-03 | How the taxpayer / participant is identified on each call | Headers / endpoint URLs |
| MV-04 | Invoice submission endpoint and accepted payload (PINT AE XML, JSON or both) | Endpoint "Submit Invoice" + request mapping |
| MV-05 | Credit note and self-billed submission | Endpoints |
| MV-06 | Pre-submission validation endpoint, if any | Endpoint "Validate Invoice" |
| MV-07 | Submission response: document ID, status values, error structure | Response mapping |
| MV-08 | ASP, FTA reporting and Peppol delivery status endpoints and values | Status endpoints + response mapping |
| MV-09 | XML and PDF retrieval | Download endpoints, approved hosts |
| MV-10 | Participant lookup / registration | Participant endpoints |
| MV-11 | Incoming invoice retrieval | Endpoint or webhook |
| MV-12 | Webhook registration, events, payload, signature, retries | Webhook configuration |
| MV-13 | Idempotency mechanism | Endpoint idempotency settings |
| MV-14 | Rate limits, timeouts, payload limits | Endpoint timeout / retry |
| MV-15 | Sandbox credentials and official sample requests / responses | Replace the mock fixtures in the tests |

## Steps once documentation arrives

1. Create an ASP REST API Configuration (`asp_code` e.g. `microvista`) from the documentation.
2. Open Microvista Settings, link the configuration, enter participant details, save.
3. Put the credentials on the linked ASP Connection.
4. Verify Credentials, then submit sandbox documents and compare with the official samples.
5. Replace `MOCK_CONTRACT` in `asp_connectors/uae/microvista/tests/` with official fixtures.
6. Set the directory entry to Sandbox Tested; Production Verified only after production checks.

If Microvista needs something configuration cannot express (a signature scheme, a multi-step
submission), implement it inside `asp_connectors/uae/microvista/` only.

The automated Microvista tests use a mock contract and a mock server. They prove the adapter runs a
configured contract; they say nothing about Microvista's real API.
