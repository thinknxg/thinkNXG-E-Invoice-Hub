# Installation, upgrade, testing and go-live

## Install

```bash
bench get-app /path/to/thinknxg_einvoice_hub
bench --site <site> install-app thinknxg_einvoice_hub
bench --site <site> migrate
```

Creates roles, connector / adapter catalogues, the UAE and Oman compliance profiles, the ASP directory
(86 entries) and the Wafeq preset. Scheduler and workers must run.

## Upgrade from 0.1.x to 0.2.0

```bash
bench --site <site> backup
bench update --apps thinknxg_einvoice_hub      # or replace the app folder
bench --site <site> migrate
```

`migrate` adds the new DocTypes and fields and runs the patch
`patches.v0_2.backfill_lifecycle_status`, which derives Internal Validation, ASP Submission and
Delivery for existing transactions from their old status. FTA Reporting stays "Not Applicable" for
old documents because it was not recorded. Existing statuses, API responses and webhook URLs are
unchanged; the API responses gain fields.

## Upgrade from 0.2.x to 0.3.0 (Oman)

```bash
bench --site <site> backup
bench update --apps thinknxg_einvoice_hub      # or replace the app folder
bench pip install saxonche                     # optional: official PINT OM Schematron
bench --site <site> migrate
```

`migrate` adds the Compliance Tax Rule table and the fields `country_code`, `document_uuid` (already present),
`peppol_delivery_expected`, creates the `om_pint_om` Compliance Profile and runs
`patches.v0_3.country_code_backfill`, which only fills empty `country_code` values (AE for UAE profiles). UAE
documents are generated exactly as before (byte-identical regression goldens). Tested on a v0.2.0 site with UAE
data: transactions, payloads and validation messages unchanged.

Rollback: disable the Oman Compliance Profile, restore the previous app version and run `bench migrate`; the added
columns stay unused. Restore the backup only if you need to remove them.

Oman configuration: `OMAN_FAWTARA_CONFIGURATION.md`. Oman checks on a site:
`bench --site <site> execute thinknxg_einvoice_hub.tests.bench_oman.run --kwargs "{'resources': '/opt/pint-om-resources-1.0.1'}"`.

## Automated tests (no bench needed)

```bash
python -m unittest discover -s thinknxg_einvoice_hub/tests -t .
python -m unittest thinknxg_einvoice_hub.asp_connectors.uae.microvista.tests.test_microvista
```

Optional official checks (PINT OM Schematron, UBL 2.1 XSD): see `OMAN_FAWTARA_TESTING.md`.

## Sandbox testing with the mock ASP

1. `python -m thinknxg_einvoice_hub.tests.mock_asp 8765` (a mock, not any real provider).
2. In E-Invoice Hub Settings enable "Allow Connections to Private Network Hosts" and
   "Allow Plain HTTP Endpoints" (test systems only).
3. Create an ASP REST API Configuration pointing at `http://127.0.0.1:8765` with the endpoints in
   `tests/mock_asp.py`, an ASP Connection with adapter `rest_config`, and a company profile.
4. Submit invoices; numbers containing `REJECT` or `FLAKY` exercise refusal and retry.

## Production checklist

- [ ] HTTPS on the site; "Allow Plain HTTP Endpoints" and "Allow Connections to Private Network Hosts" off
      (the second only on for on-premise ERPs in single-organisation deployments).
- [ ] Provider's directory entry reflects reality; Production Verified ticked only after tests.
- [ ] ASP contract verified in the provider's sandbox with official samples.
- [ ] Official PINT AE 1.0.5 resources installed and `official_validation` set (docs/UAE_PINT_AE_VALIDATION.md).
- [ ] UAE company profiles carry legal registration ID, type and authority.
- [ ] Generated PINT AE documents accepted in the ASP's sandbox (passing the Schematron is not ASP acceptance).
- [ ] Webhook secrets set per connection; provider retries observed in Webhook Event.
- [ ] Idempotency enabled on submission endpoints wherever the provider supports it.
- [ ] Each tenant's users listed on its Integration Tenant with the right access level.
- [ ] Scheduler and workers monitored; Integration Log retention set.
- [ ] Credential rotation procedure agreed (update the ASP / ERP Connection; tokens are re-fetched).
- [ ] Backups and restore tested.
