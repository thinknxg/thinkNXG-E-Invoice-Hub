# Oman Fawtara: Configuration

## 1. Compliance Profile `om_pint_om`

Created automatically by install / migrate. Fields:

| Field | Value |
| --- | --- |
| Engine Code | `om_pint_om` |
| Country Code | OM |
| Customization ID / Profile ID | `urn:peppol:pint:billing-1@om-1` / `urn:peppol:bis:billing` |
| Self-Billing Customization ID / Profile ID | `urn:peppol:pint:selfbilling-1@om-1` / `urn:peppol:bis:selfbilling` |
| Participant Identifier Scheme | 0248 |
| Default Currency | OMR (tax currency) |
| Environment | Sandbox or Production (informational) |
| Engine Settings (JSON) | see below |
| Tax Rules | optional effective-dated rates and codes |

### Engine Settings (JSON)

| Key | Default | Meaning |
| --- | --- | --- |
| `schematron_dir` | none | Folder of the unzipped official PINT OM **Billing** resources (contains `trn-invoice/schematron`, `trn-creditnote/schematron`) |
| `selfbilling_schematron_dir` | none | Same for the **Self-Billing** resources |
| `official_validation` | `if_configured` | `off`; `if_configured` (run when the folder is set, warn otherwise); `required` (a document cannot be submitted unless the official Schematron ran and passed) |
| `document_amount_decimals` | 2 | Decimals of document-level totals (official ruleset 1.0.1 allows at most 2) |
| `uuid_namespace` | `e0bc4ac8-b025-46e5-a76d-0c893fc3027e` | UUIDv5 namespace fixed by the OTA; change only if the OTA changes it |
| `always_seller_uuid` | false | Also compute the Seller UUID / QR for B2B invoices |
| `standard_rate_schedule` | `[["2021-04-16", "5"]]` | Effective-dated standard rate (Tax Rules rows override it) |
| `category_codes`, `exemption_codes`, `zero_rating_codes` | official code lists | Overrides if a later release changes them |
| `vatin_pattern` | `^OM\d{10}$` | VATIN format |

Example:

```json
{"schematron_dir": "/opt/pint-om-resources-1.0.1/billing",
 "selfbilling_schematron_dir": "/opt/pint-om-resources-1.0.1/sb",
 "official_validation": "required"}
```

### Installing the official resources

1. Download `resources.zip` from https://docs.peppol.eu/poac/om/pint-om/ (Billing) and the Self-Billing equivalent.
2. Unzip to a folder readable by the bench user, e.g. `/opt/pint-om-resources-1.0.1/billing` and `.../sb`.
3. `bench pip install saxonche` (Saxon-HE, XSLT 3.0).
4. Set the engine settings above. `GET api.oman.get_country_profile` shows the ruleset version it found.

The resources are not shipped with the app; install a new release when OpenPeppol publishes one.

### Tax Rules (child table)

| Column | Use |
| --- | --- |
| Tax Category | STANDARD, ZERO_RATED, EXEMPT, OUT_OF_SCOPE |
| Country Category Code | S, Z, E, O (overrides the built-in mapping) |
| Rate (%) / Effective From / Effective To | STANDARD rows build the rate schedule |
| Tax Treatment, Regulatory Reference, Active | documentation and switch |

Leave the table empty to use the built-in Oman values.

## 2. Company Integration Profile (seller / buyer company)

| Field | Oman value |
| --- | --- |
| VAT Registration Number | VATIN, `OM` + 10 digits |
| Network Address | leave empty: the VATIN is used with scheme 0248 |
| Legal Registration ID / Type | e.g. commercial registration number / `CR` (CL-06-OM) |
| Street, Additional Street, Address Line 3, City, Postal Code | all required on Oman invoices (IBR-010-OM) |
| Emirate / Zone Code | CL-13-OM: MO (mainland), SEZAD, SHRFZ, SLLFZ, AFZ, OTH |
| Country Code | OM |
| Contact Telephone | required (IBR-011-OM) |
| Compliance Profile | `om_pint_om` |
| ASP Connection | the Oman provider connection |

## 3. ERPNext / thinkNXG ERP connection (Extra Configuration)

```json
{
  "default_country": "OM",
  "tax_category_map": {"Oman Zero Food - ABC": {"category": "ZERO_RATED", "exemption_reason_code": "VATZR-OM-01"},
                       "Oman Exempt Rent - ABC": {"category": "EXEMPT", "exemption_reason_code": "VATEX-OM-04"}},
  "item_field_map": {"item_type": "custom_om_item_type", "commodity_code": "custom_hs_code",
                     "industry_code": "custom_isic_code", "service_type": "custom_om_service_type"},
  "credit_reason_field": "custom_om_credit_reason",
  "default_credit_reason_code": "CAN",
  "b2c_field": "custom_om_b2c",
  "address_line3_field": "custom_address_line3",
  "subdivision_map": {"Muscat": "MO", "Sohar Free Zone": "SHRFZ"},
  "uuid_field": "custom_om_invoice_uuid"
}
```

The custom fields are created in the ERP (Sales Invoice Item / Sales Invoice / Address). The posting time becomes
the invoice issue time automatically.

## 4. Provider connection

Create an **ASP Connection** with the provider's adapter (or `rest_config` + an ASP REST API Configuration) in the
**Sandbox** environment. Map the provider's MLS / status fields to the platform fields `invoice_mls_code` and
`tdd_mls_code` (or directly to `fta_status` / `delivery_status`). Credentials go in the connection's password
fields; they are never returned by the API or written to logs. The built-in `sandbox` adapter can be used to try
the Oman flow end to end; it transmits nothing.

## 5. Rollback

The Oman changes are additive (new engine, optional canonical fields, new columns `country_code`,
`document_uuid`, `peppol_delivery_expected`, new child table, new status value "Reported"). To roll back:
disable the `om_pint_om` Compliance Profile, take a backup, reinstall the previous app version and run
`bench migrate`; the extra columns stay unused. UAE documents are generated exactly as before either way.
