#!/usr/bin/env python3
"""Generator for thinkNXG E-Invoice Hub DocTypes and workspace.

Usage: python3 gen_doctypes.py <path-to-app-package>
"""
import json
import os
import sys

ROOT = sys.argv[1]
MODULE = "E Invoice Hub"
MOD_DIR = os.path.join(ROOT, "e_invoice_hub")
TS = "2026-11-12 12:00:00.000000"
ACR = {"Erp": "ERP", "Asp": "ASP", "Id": "ID", "Api": "API", "Url": "URL", "Tin": "TIN",
       "Ssl": "SSL", "Sha256": "SHA-256", "Json": "JSON"}

ADMIN, TADMIN, TUSER = "E-Invoice Hub Admin", "E-Invoice Hub Tenant Admin", "E-Invoice Hub User"


def label(fn):
    return " ".join(ACR.get(w.title(), w.title()) for w in fn.split("_"))


def F(fn, ft="Data", lbl=None, **kw):
    d = {"fieldname": fn, "fieldtype": ft, "label": lbl or label(fn)}
    d.update(kw)
    return d


def S(fn, lbl=None, **kw):
    d = {"fieldname": fn, "fieldtype": "Section Break"}
    if lbl:
        d["label"] = lbl
    d.update(kw)
    return d


def C(fn):
    return {"fieldname": fn, "fieldtype": "Column Break"}


def sel(*opts):
    return "\n".join(opts)


def perm(role, kind):
    p = {"role": role, "read": 1, "report": 1, "export": 1, "print": 1}
    if kind == "full":
        p.update({"write": 1, "create": 1, "delete": 1, "email": 1, "share": 1})
    elif kind == "manage":  # read + write + delete, no manual create
        p.update({"write": 1, "delete": 1})
    return p


def perms(admin="full", tadmin=None, tuser=None):
    out = [perm("System Manager", admin), perm(ADMIN, admin)]
    if tadmin:
        out.append(perm(TADMIN, tadmin))
    if tuser:
        out.append(perm(TUSER, tuser))
    return out


AUTH = sel("None", "API Key and Secret", "Basic", "Bearer Token", "OAuth2 Client Credentials")
DOC_TYPES = sel("INVOICE", "CREDIT_NOTE", "SELF_BILLING_INVOICE", "SELF_BILLING_CREDIT_NOTE")
STATUSES = sel("Received", "Normalized", "Validated", "Validation Failed", "Submitted", "Delivered", "Reported",
               "Rejected", "Retrying", "Failed", "Duplicate", "Cancelled")


def connection_fields(kind):
    """Shared credential block for ERP Connection / ASP Connection."""
    return [
        S("sb_auth", "Endpoint and Authentication"),
        F("base_url", "Data", "Base URL", length=500),
        F("auth_type", "Select", options=AUTH, default="API Key and Secret"),
        F("verify_ssl", "Check", "Verify SSL Certificate", default="1"),
        F("timeout", "Int", "Timeout (seconds)", default="30"),
        C("cb_auth"),
        F("api_key", "Data", "API Key", depends_on="eval:doc.auth_type=='API Key and Secret'"),
        F("api_secret", "Password", "API Secret / Token",
          depends_on="eval:['API Key and Secret','Bearer Token'].includes(doc.auth_type)"),
        F("username", "Data", depends_on="eval:doc.auth_type=='Basic'"),
        F("password", "Password", depends_on="eval:doc.auth_type=='Basic'"),
        F("token_url", "Data", "Token URL", length=500,
          depends_on="eval:doc.auth_type=='OAuth2 Client Credentials'"),
        F("client_id", "Data", "Client ID", depends_on="eval:doc.auth_type=='OAuth2 Client Credentials'"),
        F("client_secret", "Password", depends_on="eval:doc.auth_type=='OAuth2 Client Credentials'"),
        F("scope", "Data", depends_on="eval:doc.auth_type=='OAuth2 Client Credentials'"),
        S("sb_webhook", "Webhooks"),
        F("webhook_secret", "Password",
          description="Shared secret used to verify the HMAC-SHA256 signature of incoming webhooks. "
                      "Webhooks are rejected while this is empty."),
        F("webhook_help", "HTML", "Webhook URL"),
        S("sb_extra", "Advanced Configuration"),
        F("extra_config", "Code", "Extra Configuration (JSON)", options="JSON",
          description=f"Connector-specific settings for this {kind}. See the app README."),
        S("sb_test", "Connection Test"),
        F("last_test_status", "Data", read_only=1, no_copy=1),
        C("cb_test"),
        F("last_tested_on", "Datetime", read_only=1, no_copy=1),
    ]


DOCTYPES = {
    # ------------------------------------------------------------------ tenancy
    "Integration Tenant": dict(
        autoname="field:tenant_name", naming_rule="By fieldname", perms=perms("full", "read"),
        fields=[
            F("tenant_name", reqd=1, unique=1, in_list_view=1),
            F("tenant_code", reqd=1, unique=1, in_list_view=1,
              description="Short code used in API calls, e.g. ACME"),
            F("status", "Select", options=sel("Active", "Suspended"), default="Active", in_list_view=1,
              in_standard_filter=1),
            C("cb1"),
            F("contact_email", options="Email"),
            F("country", "Link", options="Country"),
            S("sb_users", "Tenant Users"),
            F("users", "Table", "Users", options="Integration Tenant User",
              description="Users listed here can only see this tenant's connections, companies and invoices."),
            S("sb_notes", "Notes"),
            F("notes", "Small Text"),
        ]),
    "Integration Tenant User": dict(
        istable=1,
        fields=[
            F("user", "Link", options="User", reqd=1, in_list_view=1),
            F("access", "Select", options=sel("Admin", "User", "API"), default="User", in_list_view=1),
        ]),
    # ------------------------------------------------------------------ catalogs
    "ERP Connector": dict(
        autoname="field:connector_code", naming_rule="By fieldname", title_field="connector_name",
        perms=perms("full", "read", "read"),
        fields=[
            F("connector_name", reqd=1, in_list_view=1),
            F("connector_code", reqd=1, unique=1, in_list_view=1),
            F("status", "Select", options=sel("Available", "Beta", "Planned"), default="Planned",
              in_list_view=1, in_standard_filter=1),
            C("cb1"),
            F("integration_methods", "Small Text"),
            F("connector_class", "Data", read_only=1, length=255,
              description="Resolved from the connector registry; informational."),
            S("sb_cap", "Advertised Capabilities"),
            F("supports_fetch_invoice", "Check", read_only=1),
            F("supports_fetch_pending", "Check", "Supports Fetch Pending Invoices", read_only=1),
            F("supports_webhooks", "Check", read_only=1),
            C("cb2"),
            F("supports_purchase_invoice", "Check", "Supports Purchase Invoice Creation", read_only=1),
            F("supports_status_update", "Check", read_only=1),
            S("sb_desc"),
            F("description", "Small Text"),
        ]),
    "ASP Provider": dict(
        autoname="field:provider_code", naming_rule="By fieldname", title_field="provider_name",
        perms=perms("full", "read", "read"),
        fields=[
            F("provider_name", reqd=1, in_list_view=1),
            F("provider_code", reqd=1, unique=1, in_list_view=1),
            F("status", "Select", options=sel("Available", "Beta", "Planned"), default="Planned",
              in_list_view=1, in_standard_filter=1),
            C("cb1"),
            F("website", "Data", length=255),
            F("adapter_class", "Data", read_only=1, length=255,
              description="Resolved from the adapter registry; informational."),
            S("sb_cap", "Advertised Capabilities"),
            F("supports_submit", "Check", "Supports Submission", read_only=1),
            F("supports_status", "Check", "Supports Status Query", read_only=1),
            C("cb2"),
            F("supports_inbound", "Check", "Supports Inbound Documents", read_only=1),
            F("supports_webhooks", "Check", read_only=1),
            S("sb_desc"),
            F("description", "Small Text"),
        ]),
    "Compliance Profile": dict(
        autoname="field:profile_code", naming_rule="By fieldname", title_field="profile_name",
        perms=perms("full", "read", "read"),
        fields=[
            F("profile_name", reqd=1, in_list_view=1),
            F("profile_code", reqd=1, unique=1, in_list_view=1),
            F("country", "Link", options="Country", in_list_view=1),
            F("enabled", "Check", default="1"),
            C("cb1"),
            F("standard", in_list_view=1),
            F("spec_version", "Data", "Specification Version"),
            F("engine_code", reqd=1, description="Compliance engine registered in the app, e.g. uae_pint_ae, om_pint_om"),
            F("country_code", "Data", "Country Code (ISO 3166-1)", length=2, in_list_view=1, in_standard_filter=1),
            F("default_currency", "Data", length=3),
            S("sb_ids", "Specification Identifiers"),
            F("customization_id", "Data", "Customization ID", length=255),
            F("profile_id", "Data", "Profile ID", length=255),
            C("cb2"),
            F("selfbilling_customization_id", "Data", "Self-Billing Customization ID", length=255),
            F("selfbilling_profile_id", "Data", "Self-Billing Profile ID", length=255),
            F("endpoint_scheme", "Data", "Participant Identifier Scheme"),
            S("sb_settings", "Engine Settings", collapsible=1),
            F("environment", "Select", options=sel("Sandbox", "Production"), default="Sandbox",
              description="Informational: which provider environment this profile is used with."),
            F("engine_settings", "Code", "Engine Settings (JSON)", options="JSON",
              description="Country-specific settings passed to the compliance engine. Oman example: "
                          "{\"schematron_dir\": \"/opt/pint-om-resources-1.0.1\", \"official_validation\": \"required\"}. "
                          "See docs/OMAN_FAWTARA_CONFIGURATION.md."),
            S("sb_tax", "Tax Rules", collapsible=1),
            F("tax_rules", "Table", "Tax Rules", options="Compliance Tax Rule",
              description="Effective-dated VAT rates and category codes. Empty: the engine's built-in table applies."),
        ]),
    "Compliance Tax Rule": dict(
        istable=1,
        fields=[
            F("tax_category", "Select", in_list_view=1, reqd=1,
              options=sel("STANDARD", "ZERO_RATED", "EXEMPT", "OUT_OF_SCOPE", "REVERSE_CHARGE", "MARGIN_SCHEME")),
            F("tax_code", "Data", "Country Category Code", in_list_view=1, length=10),
            F("rate", "Float", "Rate (%)", in_list_view=1, precision="2"),
            F("treatment", "Data", "Tax Treatment"),
            F("effective_from", "Date", in_list_view=1, reqd=1),
            F("effective_to", "Date"),
            F("regulatory_reference", "Data", length=255),
            F("active", "Check", default="1", in_list_view=1),
        ]),
    # ------------------------------------------------------------------ tenant config
    "ERP Connection": dict(
        autoname="ERPC-.#####", naming_rule="Expression (old style)", title_field="connection_name",
        perms=perms("full", "full", "read"), custom_controller=True, js=True,
        fields=[
            F("connection_name", reqd=1, in_list_view=1),
            F("tenant", "Link", options="Integration Tenant", reqd=1, in_list_view=1, in_standard_filter=1,
              set_only_once=1),
            F("erp_connector", "Link", options="ERP Connector", reqd=1, in_list_view=1, in_standard_filter=1),
            C("cb0"),
            F("enabled", "Check", default="1", in_list_view=1),
            F("mapping_configuration", "Link", options="Mapping Configuration",
              description="Optional field mapping from this ERP's payload to the canonical invoice."),
            *connection_fields("ERP connection")[:-4],
            S("sb_poll", "Scheduled Retrieval"),
            F("polling_enabled", "Check", "Retrieve Pending Invoices Automatically"),
            F("polling_filters", "Code", "Retrieval Filters (JSON)", options="JSON",
              depends_on="polling_enabled"),
            C("cb_poll"),
            F("last_polled_on", "Datetime", read_only=1, no_copy=1),
            *connection_fields("ERP connection")[-4:],
        ]),
    "ASP Connection": dict(
        autoname="ASPC-.#####", naming_rule="Expression (old style)", title_field="connection_name",
        perms=perms("full", "full", "read"), custom_controller=True, js=True,
        fields=[
            F("connection_name", reqd=1, in_list_view=1),
            F("tenant", "Link", options="Integration Tenant", reqd=1, in_list_view=1, in_standard_filter=1,
              set_only_once=1),
            F("asp_provider", "Link", options="ASP Provider", reqd=1, in_list_view=1, in_standard_filter=1),
            C("cb0"),
            F("enabled", "Check", default="1", in_list_view=1),
            F("environment", "Select", options=sel("Sandbox", "Production"), default="Sandbox", in_list_view=1),
            F("payload_format", "Select", options=sel("Compliance Document", "Canonical JSON"),
              default="Compliance Document",
              description="Send the generated compliance document (e.g. PINT AE UBL XML) or the canonical "
                          "JSON when the provider performs its own conversion."),
            *connection_fields("ASP connection"),
        ]),
    "Company Integration Profile": dict(
        autoname="CIP-.#####", naming_rule="Expression (old style)", title_field="company_name",
        perms=perms("full", "full", "read"), custom_controller=True,
        fields=[
            F("company_name", "Data", "Legal Name", reqd=1, in_list_view=1),
            F("trading_name"),
            F("tenant", "Link", options="Integration Tenant", reqd=1, in_list_view=1, in_standard_filter=1,
              set_only_once=1),
            F("enabled", "Check", default="1", in_list_view=1),
            C("cb0"),
            F("tax_id", "Data", "VAT Registration Number (TRN / VATIN)", reqd=1, in_list_view=1, search_index=1,
              description="UAE: 15-digit TRN. Oman: VATIN, OM followed by 10 digits."),
            F("tin", "Data", "Network Address (TIN / VATIN)",
              description="Network participant identifier. UAE: derived from the first 10 digits of the TRN "
                          "(scheme 0235). Oman: the VATIN itself (scheme 0248). Derived when left empty."),
            F("participant_id", "Data", "Network Participant ID", read_only=1),
            F("legal_registration_id", "Data", "Legal Registration ID"),
            F("legal_registration_type", "Select",
              options=sel("", "TL", "EID", "PAS", "CD", "CR", "TIN", "CID", "PASNUM", "OTHID", "ICID", "SZLN"),
              description="UAE: TL = Trade Licence, EID = Emirates ID, PAS = Passport, CD = Cabinet Decision. "
                          "Oman (CL-06-OM): CR = Commercial Registration, TIN, CID = Civil ID, PASNUM = Passport, "
                          "OTHID = Other, ICID = Importer Customs ID, SZLN = Special Zone Licence"),
            S("sb_addr", "Registered Address"),
            F("street"),
            F("additional_street"),
            F("address_line", "Data", "Address Line 3",
              description="Required on Oman invoices together with street, additional street, city and postal code (IBR-010-OM)."),
            F("city"),
            C("cb_addr"),
            F("subdivision", "Data", "Emirate / Zone Code",
              description="UAE emirate: AUH, DXB, SHJ, AJM, UAQ, RAK, FUJ. Oman (CL-13-OM): MO = mainland, "
                          "SEZAD, SHRFZ, SLLFZ, AFZ, OTH"),
            F("postal_code"),
            F("country", "Link", options="Country"),
            F("country_code", "Data", "Country Code (ISO 3166-1)", length=2, default="AE", reqd=1),
            S("sb_contact", "Contact"),
            F("contact_name"),
            F("contact_phone", "Data", "Contact Telephone", options="Phone",
              description="Required on Oman invoices (seller telephone, IBR-011-OM)."),
            C("cb_contact"),
            F("contact_email", "Data", "Contact Email", options="Email"),
            S("sb_route", "Routing"),
            F("erp_connection", "Link", "ERP Connection", options="ERP Connection"),
            F("asp_connection", "Link", "ASP Connection", options="ASP Connection"),
            F("compliance_profile", "Link", options="Compliance Profile", reqd=1),
            C("cb_route"),
            F("auto_submit", "Check", "Submit to ASP Automatically", default="1"),
            F("sync_status_to_erp", "Check", "Send Status Back to ERP", default="1"),
            F("inbound_action", "Select", "Inbound Invoice Action",
              options=sel("Create Draft Purchase Invoice", "Hold in Hub"),
              default="Create Draft Purchase Invoice"),
        ]),
    "Mapping Configuration": dict(
        autoname="MAP-.#####", naming_rule="Expression (old style)", title_field="config_name",
        perms=perms("full", "full", "read"), custom_controller=True,
        fields=[
            F("config_name", "Data", "Mapping Name", reqd=1, in_list_view=1),
            F("tenant", "Link", options="Integration Tenant", in_list_view=1, in_standard_filter=1,
              description="Leave empty to make this a shared template (hub administrators only)."),
            F("erp_connector", "Link", options="ERP Connector", in_list_view=1),
            C("cb0"),
            F("enabled", "Check", default="1"),
            F("line_source_path", "Data", "Source Path of Invoice Lines",
              description="Path of the line array in the ERP payload, e.g. items or d.results"),
            S("sb_rules", "Field Mapping"),
            F("rules", "Table", "Mapping Rules", options="Mapping Rule"),
            S("sb_defaults", "Static Defaults"),
            F("defaults", "Code", "Canonical Defaults (JSON)", options="JSON",
              description="Canonical values applied before the mapping rules, e.g. "
                          "{\"document\": {\"currency\": \"AED\"}}"),
        ]),
    "Mapping Rule": dict(
        istable=1,
        fields=[
            F("scope", "Select", options=sel("Header", "Line"), default="Header", in_list_view=1, reqd=1),
            F("source_path", "Data", "ERP Field Path", in_list_view=1, length=255),
            F("canonical_path", "Data", "Canonical Field Path", in_list_view=1, reqd=1, length=255),
            F("transform", "Select", in_list_view=1,
              options=sel("None", "Upper", "Lower", "Strip", "Date", "Number", "Value Map", "Constant", "Boolean"),
              default="None"),
            F("transform_arg", "Small Text", "Transform Argument",
              description="Date: input format (e.g. %d/%m/%Y). Value Map: JSON object. Constant: the value."),
            F("default_value", "Data"),
            F("required", "Check", in_list_view=1),
        ]),
    # ------------------------------------------------------------------ runtime
    "Invoice Transaction": dict(
        autoname="EINV-.YYYY.-.#######", naming_rule="Expression (old style)", title_field="invoice_number",
        perms=perms("manage", "read", "read"), js=True, list_js=True,
        fields=[
            F("tenant", "Link", options="Integration Tenant", reqd=1, in_standard_filter=1, read_only=1,
              search_index=1),
            F("company_profile", "Link", options="Company Integration Profile", in_list_view=1,
              in_standard_filter=1, read_only=1),
            F("direction", "Select", options=sel("Outbound", "Inbound"), reqd=1, in_list_view=1,
              in_standard_filter=1, read_only=1),
            F("document_type", "Select", options=DOC_TYPES, default="INVOICE", read_only=1),
            C("cb0"),
            F("status", "Select", options=STATUSES, default="Received", in_list_view=1, in_standard_filter=1,
              read_only=1, search_index=1),
            F("invoice_number", in_list_view=1, read_only=1, search_index=1),
            F("invoice_date", "Date", read_only=1),
            F("document_uuid", "Data", "Document UUID", read_only=1, search_index=1,
              description="Invoice UUID where the country requires one (Oman BTOM-002)."),
            F("country_code", "Data", "Country", length=2, read_only=1, in_standard_filter=1, search_index=1,
              description="Country of the compliance engine that processed this document."),
            F("peppol_delivery_expected", "Check", "Peppol Delivery Expected", default="1", read_only=1,
              description="Cleared when the receiver is outside Peppol (e.g. Oman B2C or export): the provider only "
                          "reports to the tax authority, and a confirmed report completes the document as 'Reported'."),
            F("duplicate_of", "Link", options="Invoice Transaction", read_only=1),
            S("sb_parties", "Parties and Totals"),
            F("supplier_name", read_only=1),
            F("supplier_tax_id", "Data", "Supplier Tax ID", read_only=1),
            F("customer_name", read_only=1),
            F("customer_tax_id", "Data", "Customer Tax ID", read_only=1),
            C("cb1"),
            F("currency", "Data", length=3, read_only=1),
            F("subtotal", "Float", precision="3", read_only=1),
            F("tax_total", "Float", precision="3", read_only=1),
            F("grand_total", "Float", precision="3", read_only=1, in_list_view=1),
            S("sb_erp", "ERP"),
            F("erp_connection", "Link", "ERP Connection", options="ERP Connection", read_only=1),
            F("erp_document_id", "Data", "ERP Document ID", read_only=1, search_index=1),
            C("cb2"),
            F("erp_sync_status", "Select", "ERP Sync Status",
              options=sel("Not Applicable", "Pending", "Synced", "Failed"), default="Not Applicable", read_only=1),
            F("erp_sync_message", "Small Text", "ERP Sync Message", read_only=1),
            S("sb_asp", "ASP / Network"),
            F("asp_connection", "Link", "ASP Connection", options="ASP Connection", read_only=1),
            F("compliance_profile", "Link", options="Compliance Profile", read_only=1),
            F("asp_reference", "Data", "ASP Reference", read_only=1, search_index=1),
            C("cb3"),
            F("asp_status", "Data", "ASP Status", read_only=1),
            F("asp_message", "Small Text", "ASP Message", read_only=1),
            F("asp_error_code", "Data", "ASP Error Code", read_only=1),
            F("submitted_at", "Datetime", read_only=1),
            F("delivered_at", "Datetime", read_only=1),
            S("sb_val", "Validation"),
            F("validation_messages", "Table", options="Invoice Validation Message", read_only=1),
            S("sb_proc", "Processing"),
            F("idempotency_key", "Data", read_only=1, search_index=1, length=255),
            F("schema_version", "Data", "Canonical Schema Version", read_only=1),
            C("cb4"),
            F("retry_count", "Int", read_only=1),
            F("next_retry_at", "Datetime", read_only=1),
            F("last_error", "Small Text", read_only=1),
        ]),
    "Invoice Validation Message": dict(
        istable=1,
        fields=[
            F("severity", "Select", options=sel("Error", "Warning", "Info"), in_list_view=1),
            F("rule_id", "Data", "Rule", in_list_view=1),
            F("field_path", "Data", "Field", in_list_view=1, length=255),
            F("message", "Small Text", in_list_view=1),
        ]),
    "Invoice Payload": dict(
        autoname="hash", naming_rule="Random", perms=perms("read", "read", "read"), custom_controller=True,
        fields=[
            F("tenant", "Link", options="Integration Tenant", reqd=1, read_only=1, search_index=1),
            F("transaction", "Link", options="Invoice Transaction", reqd=1, in_list_view=1, read_only=1,
              search_index=1),
            F("payload_type", "Select", reqd=1, in_list_view=1, in_standard_filter=1, read_only=1,
              options=sel("Source ERP", "Canonical", "Compliance Document", "ASP Request", "ASP Response",
                          "ASP Inbound", "ERP Response", "ASP Document")),
            C("cb0"),
            F("content_format", "Select", options=sel("JSON", "XML", "Text"), default="JSON", in_list_view=1,
              read_only=1),
            F("sha256", "Data", "SHA-256", read_only=1, length=64),
            S("sb_content"),
            F("content", "Code", read_only=1),
        ]),
    "Webhook Event": dict(
        autoname="hash", naming_rule="Random", perms=perms("manage", "read"),
        fields=[
            F("tenant", "Link", options="Integration Tenant", reqd=1, read_only=1, in_standard_filter=1,
              search_index=1),
            F("source_type", "Select", options=sel("ERP", "ASP"), reqd=1, in_list_view=1, read_only=1,
              in_standard_filter=1),
            F("erp_connection", "Link", "ERP Connection", options="ERP Connection", read_only=1),
            F("asp_connection", "Link", "ASP Connection", options="ASP Connection", read_only=1),
            C("cb0"),
            F("status", "Select", options=sel("Received", "Processed", "Ignored", "Failed"), default="Received",
              in_list_view=1, in_standard_filter=1, read_only=1),
            F("event_type", in_list_view=1, read_only=1),
            F("signature_valid", "Check", read_only=1, in_list_view=1),
            F("transaction", "Link", options="Invoice Transaction", read_only=1),
            F("received_at", "Datetime", read_only=1),
            S("sb_payload", "Payload"),
            F("headers", "Code", options="JSON", read_only=1),
            F("payload", "Code", read_only=1),
            F("error", "Small Text", read_only=1),
        ]),
    "Integration Audit Log": dict(
        autoname="hash", naming_rule="Random", perms=perms("read", "read", "read"),
        fields=[
            F("tenant", "Link", options="Integration Tenant", read_only=1, in_standard_filter=1, search_index=1),
            F("transaction", "Link", options="Invoice Transaction", read_only=1, in_list_view=1, search_index=1),
            F("event", in_list_view=1, read_only=1, in_standard_filter=1),
            C("cb0"),
            F("level", "Select", options=sel("Info", "Warning", "Error"), default="Info", in_list_view=1,
              read_only=1, in_standard_filter=1),
            F("actor", "Link", options="User", read_only=1),
            F("logged_at", "Datetime", read_only=1),
            S("sb_msg"),
            F("message", "Small Text", in_list_view=1, read_only=1),
            F("details", "Code", options="JSON", read_only=1),
        ]),
    "E-Invoice Hub Settings": dict(
        issingle=1, perms=[perm("System Manager", "full"), perm(ADMIN, "full")],
        fields=[
            S("sb_retry", "Retry Engine"),
            F("max_retries", "Int", default="6"),
            F("retry_base_minutes", "Int", "First Retry Delay (minutes)", default="5",
              description="Delay doubles after every failed attempt."),
            C("cb0"),
            F("poll_batch_size", "Int", "ERP Retrieval Batch Size", default="50"),
            F("status_sync_batch", "Int", "ASP Status Sync Batch Size", default="100"),
            S("sb_sec", "Security"),
            F("allow_private_hosts", "Check", "Allow Connections to Private Network Hosts",
              description="Enable only for single-organisation deployments where the ERP runs on the local "
                          "network. Keep disabled on shared multi-tenant deployments."),
        ]),
}

# ====================================================================== 0.2.0 additions
def _after(doctype, anchor, *new):
    fields = DOCTYPES[doctype]["fields"]
    i = next(n for n, f in enumerate(fields) if f["fieldname"] == anchor) + 1
    fields[i:i] = list(new)


def _field(doctype, name):
    return next(f for f in DOCTYPES[doctype]["fields"] if f["fieldname"] == name)


OPERATIONS = sel("Authenticate", "Verify Credentials", "Get Participant", "Register Participant", "Validate Invoice",
    "Submit Invoice", "Submit Credit Note", "Submit Self-Billed Invoice", "Get Invoice Status", "Get Reporting Status",
    "Get Delivery Status", "Download XML", "Download PDF", "Get Incoming Invoices", "Register Webhook",
    "Get Webhook Subscription", "Custom Operation")
REST_AUTH = sel("None", "API Key", "Bearer Token", "OAuth2 Client Credentials", "OAuth2 Authorization Code", "Basic",
    "Custom Header", "HMAC-SHA256", "JWT", "Plugin")
PLATFORM_FIELDS = sel("success", "asp_document_id", "submission_reference", "submission_status", "fta_status",
    "fta_reference", "delivery_status", "delivery_reference", "error_code", "error_message", "xml_url", "pdf_url",
    "timestamp", "invoice_mls_code", "tdd_mls_code")
INTEGRATION_STATUS = sel("Not Started", "Skeleton - Pending API Documentation", "In Development", "Sandbox Tested",
    "Production Verified")
ENV = sel("Sandbox", "Production")


def _dep(*kinds):
    return "eval:" + str(list(kinds)) + ".includes(doc.authentication_type)"


_field("ASP Provider", "status")["options"] = sel("Available", "Beta", "Development", "Planned")
_after("ASP Connection", "payload_format",
    F("accredited_provider", "Link", "Accredited Service Provider", options="UAE Accredited Service Provider",
      in_standard_filter=1),
    F("rest_configuration", "Link", "ASP REST API Configuration", options="ASP REST API Configuration",
      description="API contract used by configurable adapters. Credentials entered on this connection override "
                  "the ones stored in the configuration."),
    F("participant_id", "Data", "Provider Participant / Taxpayer ID",
      description="Identifier the provider assigned to this legal entity, available to URLs and headers as "
                  "{participant_id}."),
    F("participant_tin", "Data", "Participant TIN"))
_after("ERP Connection", "enabled",
    F("environment", "Select", options=ENV, default="Production"),
    F("sync_direction", "Select", "Synchronisation Direction",
      options=sel("Push (ERP sends to hub)", "Pull (hub retrieves from ERP)", "Both"), default="Both"))
_field("ERP Connection", "last_test_status")["label"] = "Connection Status"
_after("Company Integration Profile", "asp_connection",
    F("accredited_provider", "Link", "Accredited Service Provider", options="UAE Accredited Service Provider",
      fetch_from="asp_connection.accredited_provider", read_only=1))
_after("Invoice Transaction", "duplicate_of",
    F("validation_status", "Select", options=sel("Pending", "Passed", "Failed"), default="Pending", read_only=1,
      in_standard_filter=1))
_after("Invoice Transaction", "erp_connection", F("source_erp", "Data", "Source ERP", read_only=1))
_after("Invoice Transaction", "asp_connection",
    F("accredited_provider", "Link", "Accredited Service Provider", options="UAE Accredited Service Provider",
      read_only=1, in_standard_filter=1))
_after("Invoice Transaction", "asp_reference",
    F("submission_reference", "Data", read_only=1),
    F("asp_submission_status", "Select", "ASP Submission Status", read_only=1, in_standard_filter=1,
      options=sel("Not Submitted", "Queued", "Submitted", "Accepted", "Rejected"), default="Not Submitted"))
_after("Invoice Transaction", "delivered_at",
    S("sb_fta", "Tax Authority Reporting and Peppol Delivery"),
    F("fta_status", "Select", "Tax Authority Reporting Status", read_only=1, in_standard_filter=1, in_list_view=1,
      options=sel("Not Applicable", "Pending", "Reported", "Rejected"), default="Not Applicable"),
    F("fta_reference", "Data", "Tax Authority Reporting Reference", read_only=1),
    F("fta_message", "Small Text", "Tax Authority Message", read_only=1),
    F("fta_reported_at", "Datetime", "Tax Authority Reported At", read_only=1),
    C("cb_fta"),
    F("delivery_status", "Select", "Peppol Delivery Status", read_only=1, in_standard_filter=1, in_list_view=1,
      options=sel("Not Applicable", "Pending", "Delivered", "Failed"), default="Not Applicable"),
    F("delivery_reference", "Data", read_only=1),
    F("delivery_message", "Small Text", read_only=1))
_after("Webhook Event", "event_type",
    F("event_id", "Data", "Event ID", read_only=1, search_index=1, length=255),
    F("duplicate", "Check", "Duplicate Delivery", read_only=1))
DOCTYPES["E-Invoice Hub Settings"]["fields"] += [
    S("sb_logs", "Integration Logs"),
    F("log_retention_days", "Int", "Keep Integration Logs (days)", default="90"),
    F("allow_insecure_http", "Check", "Allow Plain HTTP Endpoints",
      description="For local test servers only. Keep disabled in production: ASP endpoints must use HTTPS."),
]

DOCTYPES.update({
    "UAE Accredited Service Provider": dict(
        autoname="field:asp_code", naming_rule="By fieldname", title_field="asp_name",
        perms=perms("full", "read", "read"), custom_controller=True,
        fields=[
            F("asp_name", "Data", "ASP Name", reqd=1, in_list_view=1),
            F("asp_code", "Data", "ASP Code", reqd=1, unique=1),
            F("legal_name", in_list_view=1),
            F("accreditation_number", in_list_view=1),
            F("enabled", "Check", default="1"),
            C("cb0"),
            F("official_website", "Data", length=255),
            F("api_documentation_url", "Data", "API Documentation URL", length=500),
            F("sandbox_url", "Data", "Sandbox URL", length=500),
            F("production_url", "Data", "Production URL", length=500),
            S("sb_status", "Three Separate Statuses"),
            F("accreditation_status", "Select", options=sel("Accredited", "Pre-Approved", "Not Verified", "Withdrawn"),
              default="Not Verified", in_list_view=1, in_standard_filter=1,
              description="As published by the Ministry of Finance. Accreditation says nothing about whether an "
                          "integration exists."),
            F("last_verification_date", "Date", description="When the accreditation entry was last checked."),
            C("cb1"),
            F("integration_status", "Select", options=INTEGRATION_STATUS, default="Not Started", in_list_view=1,
              in_standard_filter=1, description="State of the hub's own connector for this provider."),
            F("sandbox_tested", "Check"),
            C("cb2"),
            F("production_verified", "Check",
              description="Tick only after sandbox tests passed against the provider's real API. Production "
                          "connections are refused for providers without this tick."),
            S("sb_adapter", "Integration"),
            F("adapter_type", "Select", options=sel("None", "Dedicated Adapter", "Generic REST"), default="None"),
            F("adapter", "Link", "Adapter", options="ASP Provider"),
            F("rest_configuration", "Link", "REST Configuration Template", options="ASP REST API Configuration"),
            C("cb3"),
            F("authentication_type", "Data"),
            F("supported_capabilities", "Small Text", read_only=1),
            S("sb_notes"),
            F("notes", "Small Text"),
        ]),
    "ASP REST API Configuration": dict(
        autoname="ARC-.#####", naming_rule="Expression (old style)", title_field="asp_name",
        perms=perms("full", "full", "read"), custom_controller=True, js=True,
        fields=[
            F("asp_name", "Data", "ASP Name", reqd=1, in_list_view=1),
            F("asp_code", "Data", "ASP Code", reqd=1, in_list_view=1),
            F("tenant", "Link", options="Integration Tenant", in_standard_filter=1,
              description="Leave empty for a shared template (hub administrators only; templates hold no secrets)."),
            F("accredited_provider", "Link", "Accredited Service Provider", options="UAE Accredited Service Provider"),
            F("country", "Link", options="Country"),
            F("accreditation_number"),
            C("cb0"),
            F("enabled", "Check", default="1", in_list_view=1),
            F("integration_type", "Select", options=sel("REST JSON", "REST XML", "REST Mixed"), default="REST JSON"),
            F("api_version", "Data", "API Version"),
            F("environment", "Select", options=ENV, default="Sandbox", in_list_view=1),
            F("api_documentation_url", "Data", "API Documentation URL", length=500),
            S("sb_urls", "Base URLs"),
            F("sandbox_base_url", "Data", "Sandbox Base URL", length=500),
            F("production_base_url", "Data", "Production Base URL", length=500),
            F("active_base_url", "Data", "Active Base URL", length=500, read_only=1),
            C("cb1"),
            F("approved_hosts", "Small Text", "Additional Approved Hosts",
              description="One host per line. Calls are only made to the base URL hosts and the hosts listed here "
                          "(for example a token or download host)."),
            F("verify_ssl", "Check", "Verify TLS Certificate", default="1"),
            F("max_response_mb", "Int", "Maximum Response Size (MB)", default="10"),
            S("sb_auth", "Authentication"),
            F("authentication_type", "Select", options=REST_AUTH, default="None"),
            F("api_key", "Password", "API Key", depends_on=_dep("API Key", "HMAC-SHA256", "JWT", "Custom Header", "Bearer Token")),
            F("api_secret", "Password", "API Secret / Token",
              depends_on=_dep("Bearer Token", "HMAC-SHA256", "JWT", "Custom Header")),
            F("api_key_header", "Data", "API Key Header Name", default="X-API-Key",
              depends_on=_dep("API Key", "HMAC-SHA256")),
            F("api_key_prefix", "Data", "API Key Prefix", depends_on=_dep("API Key")),
            F("username", depends_on=_dep("Basic", "Custom Header")),
            F("password", "Password", depends_on=_dep("Basic", "Custom Header")),
            F("static_authorization_header", "Password",
              depends_on=_dep("Bearer Token", "Custom Header", "HMAC-SHA256"),
              description="Complete value of the Authorization header, when the provider issues a fixed one."),
            F("custom_authentication_headers", "Code", "Custom Authentication Headers (JSON)", options="JSON",
              description="Extra headers, e.g. {\"X-Client\": \"{client_id}\"}. Placeholders: {api_key}, "
                          "{api_secret}, {client_id}, {client_secret}, {username}, {password}."),
            C("cb2"),
            F("client_id", "Data", "Client ID", depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code", "JWT", "Custom Header")),
            F("client_secret", "Password", depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code", "Custom Header")),
            F("token_url", "Data", "Token URL", length=500, depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code")),
            F("token_method", "Select", options=sel("POST", "GET"), default="POST",
              depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code")),
            F("token_request_content_type", "Select",
              options=sel("application/x-www-form-urlencoded", "application/json"),
              default="application/x-www-form-urlencoded",
              depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code")),
            F("token_expiry", "Int", "Token Expiry (seconds)", default="300",
              depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code", "JWT")),
            F("refresh_token_url", "Data", "Refresh Token URL", length=500, depends_on=_dep("OAuth2 Authorization Code")),
            F("refresh_token", "Password", depends_on=_dep("OAuth2 Authorization Code")),
            F("oauth_scope", "Data", "OAuth Scope", depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code")),
            F("token_response_path", "Data", default="access_token",
              depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code")),
            F("expiry_response_path", "Data", default="expires_in",
              depends_on=_dep("OAuth2 Client Credentials", "OAuth2 Authorization Code")),
            F("hmac_signature_header", "Data", "HMAC Signature Header", default="X-Signature", depends_on=_dep("HMAC-SHA256")),
            F("hmac_timestamp_header", "Data", "HMAC Timestamp Header", default="X-Timestamp", depends_on=_dep("HMAC-SHA256")),
            F("hmac_template", "Data", "HMAC Message Template", default="{timestamp}.{method}.{path}.{body}",
              length=255, depends_on=_dep("HMAC-SHA256")),
            F("hmac_encoding", "Select", "HMAC Encoding", options=sel("hex", "base64"), default="hex",
              depends_on=_dep("HMAC-SHA256")),
            F("jwt_claims", "Code", "Additional JWT Claims (JSON)", options="JSON", depends_on=_dep("JWT")),
            F("auth_plugin", "Data", "Authentication Plugin", depends_on=_dep("Plugin"),
              description="Name registered by an installed app through the einvoice_hub_rest_auth_plugins hook."),
            S("sb_endpoints", "Endpoints"),
            F("endpoints", "Table", options="ASP REST Endpoint"),
            S("sb_headers", "Headers"),
            F("headers", "Table", options="ASP REST Header"),
            S("sb_reqmap", "Request Mapping"),
            F("request_mappings", "Table", "Request Mapping", options="ASP REST Request Mapping",
              description="Leave empty to send the compliance document (or canonical JSON) as the request body."),
            S("sb_resmap", "Response Mapping"),
            F("response_mappings", "Table", "Response Mapping", options="ASP REST Response Mapping"),
            F("incoming_list_path", "Data", "Incoming Invoices List Path",
              description="JSON path of the array in the Get Incoming Invoices response."),
            S("sb_webhook", "Webhooks"),
            F("webhooks", "Table", "Webhook Configuration", options="ASP REST Webhook Configuration"),
            S("sb_desc"),
            F("description", "Small Text"),
        ]),
    "ASP REST Endpoint": dict(istable=1, fields=[
        F("endpoint_name", in_list_view=1),
        F("operation", "Select", options=OPERATIONS, reqd=1, in_list_view=1),
        F("http_method", "Select", "HTTP Method", options=sel("GET", "POST", "PUT", "PATCH", "DELETE"), default="POST",
          in_list_view=1),
        F("relative_url", "Data", "Relative URL", length=500, in_list_view=1,
          description="e.g. /invoices/{document_id}. Placeholders: {document_id}, {participant_id}, {invoice_number}."),
        F("enabled", "Check", default="1", in_list_view=1),
        F("request_content_type", "Data", default="application/json"),
        F("response_content_type", "Data", default="application/json"),
        F("authentication_required", "Check", default="1"),
        F("timeout", "Int", "Timeout (seconds)", default="30"),
        F("retry_enabled", "Check"),
        F("maximum_retries", "Int", default="2"),
        F("idempotency_enabled", "Check"),
        F("idempotency_header", "Data", default="Idempotency-Key"),
        F("description", "Small Text"),
    ]),
    "ASP REST Header": dict(istable=1, fields=[
        F("header_name", reqd=1, in_list_view=1),
        F("header_value", "Data", length=500, in_list_view=1),
        F("value_type", "Select", options=sel("Static", "Dynamic"), default="Static", in_list_view=1),
        F("dynamic_value", "Data", in_list_view=1,
          description="now, today, timestamp, uuid, idempotency_key, environment, participant.participant_id, "
                      "metadata.invoice_number ..."),
        F("enabled", "Check", default="1", in_list_view=1),
    ]),
    "ASP REST Request Mapping": dict(istable=1, fields=[
        F("operation", "Select", options=OPERATIONS, reqd=1, in_list_view=1),
        F("source_field", "Data", length=255, in_list_view=1,
          description="e.g. invoice.document.invoice_number, invoice.lines[].quantity, document, document_base64, $now"),
        F("target_json_path", "Data", "Target JSON Path", reqd=1, length=255, in_list_view=1),
        F("data_type", "Select", options=sel("String", "Integer", "Decimal", "Boolean", "Date", "DateTime", "JSON"),
          default="String", in_list_view=1),
        F("transformation", "Data", length=500, in_list_view=1,
          description="Whitelisted steps joined by |, e.g. upper, date:%d/%m/%Y, decimal:2, map:{\"a\":\"b\"}, const:x"),
        F("condition", "Data", length=255, description="Optional, e.g. invoice.document.document_type == CREDIT_NOTE"),
        F("required", "Check"),
        F("default_value"),
        F("enabled", "Check", default="1"),
    ]),
    "ASP REST Response Mapping": dict(istable=1, fields=[
        F("response_json_path", "Data", "Response JSON Path", length=255, in_list_view=1),
        F("target_platform_field", "Select", options=PLATFORM_FIELDS, reqd=1, in_list_view=1),
        F("operation", "Select", options="\n" + OPERATIONS, description="Leave empty to apply to every operation."),
        F("transformation", "Data", length=500, in_list_view=1),
        F("default_value", in_list_view=1),
        F("required", "Check"),
        F("enabled", "Check", default="1", in_list_view=1),
    ]),
    "ASP REST Webhook Configuration": dict(istable=1, fields=[
        F("webhook_enabled", "Check", default="1", in_list_view=1),
        F("webhook_endpoint", "Data", length=500, read_only=1,
          description="Hub URL to register with the provider; shown on the ASP Connection."),
        F("authentication_type", "Select", options=sel("HMAC-SHA256", "Standard Webhooks", "Shared Secret", "JWT"), default="HMAC-SHA256",
          in_list_view=1),
        F("signing_secret", "Password"),
        F("signature_header", "Data", in_list_view=1,
          description="Header carrying the signature, secret or token. Must not be Authorization."),
        F("event_identifier_path", "Data", default="id"),
        F("event_type_path", "Data", default="event", in_list_view=1),
        F("document_identifier_path", "Data", default="document_id"),
        F("status_path", "Data", default="status"),
        F("payload_mapping", "Code", "Payload Mapping (JSON)", options="JSON",
          description="Platform field -> JSON path, e.g. {\"fta_status\": \"data.reporting.status\"}"),
        F("document_events", "Data", description="Comma-separated event types that carry an incoming document."),
        F("document_path", "Data", default="document"),
        F("document_base64", "Check", "Document is Base64"),
        F("retry_policy", "Small Text", description="Provider's redelivery policy, for reference."),
    ]),
    "Integration Log": dict(
        autoname="hash", naming_rule="Random", perms=perms("read", "read", "read"),
        fields=[
            F("tenant", "Link", options="Integration Tenant", read_only=1, in_standard_filter=1, search_index=1),
            F("logged_at", "Datetime", "Request Time", read_only=1, in_list_view=1),
            F("erp_connection", "Link", "ERP Connection", options="ERP Connection", read_only=1, in_standard_filter=1),
            F("asp_connection", "Link", "ASP Connection", options="ASP Connection", read_only=1, in_standard_filter=1),
            F("operation", read_only=1, in_list_view=1, in_standard_filter=1),
            F("transaction", "Link", options="Invoice Transaction", read_only=1, search_index=1),
            F("country_code", "Data", "Country", length=2, read_only=1, in_standard_filter=1),
            C("cb0"),
            F("result", "Select", options=sel("Success", "Failure"), read_only=1, in_list_view=1, in_standard_filter=1),
            F("http_method", "Data", "HTTP Method", read_only=1),
            F("http_status", "Int", "HTTP Status", read_only=1, in_list_view=1),
            F("duration_ms", "Int", "Duration (ms)", read_only=1, in_list_view=1),
            F("url", "Data", "URL", length=500, read_only=1),
            S("sb_detail", "Details (secrets masked)"),
            F("error", "Small Text", read_only=1),
            F("request", "Code", options="JSON", read_only=1),
            F("response", "Code", options="JSON", read_only=1),
        ]),
    "Microvista Settings": dict(
        autoname="MVS-.#####", naming_rule="Expression (old style)", title_field="settings_name",
        perms=perms("full", "full", "read"), custom_controller=True, js=True,
        fields=[
            F("settings_name", "Data", "Name", reqd=1, in_list_view=1),
            F("tenant", "Link", options="Integration Tenant", reqd=1, in_list_view=1, set_only_once=1),
            F("company_profile", "Link", "Company", options="Company Integration Profile"),
            F("environment", "Select", options=ENV, default="Sandbox", in_list_view=1),
            C("cb0"),
            F("integration_status", "Data", read_only=1, default="Skeleton - Pending API Documentation"),
            F("accreditation_number", "Data", read_only=1, default="157529"),
            S("sb_conn", "Connection and API Contract"),
            F("asp_connection", "Link", "ASP Connection", options="ASP Connection",
              description="Created automatically on save when empty. Holds credentials and the webhook secret."),
            F("rest_configuration", "Link", "ASP REST API Configuration", options="ASP REST API Configuration",
              description="Endpoints, authentication and mappings, filled from Microvista's official API documentation."),
            C("cb1"),
            F("participant_tin", "Data", "Participant TIN"),
            F("participant_id", "Data", "Microvista Participant / Taxpayer ID"),
            S("sb_ready", "Readiness"),
            F("readiness_html", "HTML", "Readiness"),
            F("last_test_status", "Small Text", read_only=1),
            F("last_tested_on", "Datetime", read_only=1),
            S("sb_notes"),
            F("notes", "Small Text"),
        ]),
})


def scrub(name):
    return name.replace(" ", "_").replace("-", "_").lower()


def classname(name):
    return name.replace(" ", "").replace("-", "")


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def build():
    for name, spec in DOCTYPES.items():
        folder = os.path.join(MOD_DIR, "doctype", scrub(name))
        fields = spec["fields"]
        names = [f["fieldname"] for f in fields]
        assert len(names) == len(set(names)), f"duplicate fieldname in {name}"
        doc = {
            "actions": [],
            "creation": TS,
            "doctype": "DocType",
            "engine": "InnoDB",
            "field_order": names,
            "fields": fields,
            "index_web_pages_for_search": 0,
            "issingle": spec.get("issingle", 0),
            "istable": spec.get("istable", 0),
            "links": [],
            "modified": TS,
            "modified_by": "Administrator",
            "module": MODULE,
            "name": name,
            "owner": "Administrator",
            "permissions": [] if spec.get("istable") else spec["perms"],
            "sort_field": "creation",
            "sort_order": "DESC",
            "states": [],
            "track_changes": 0 if spec.get("istable") else 1,
        }
        for key in ("autoname", "naming_rule", "title_field"):
            if spec.get(key):
                doc[key] = spec[key]
        if spec.get("istable"):
            doc["editable_grid"] = 1
        write(os.path.join(folder, f"{scrub(name)}.json"), json.dumps(doc, indent=1) + "\n")
        write(os.path.join(folder, "__init__.py"), "")
        if not spec.get("custom_controller"):
            write(os.path.join(folder, f"{scrub(name)}.py"),
                  "from frappe.model.document import Document\n\n\n"
                  f"class {classname(name)}(Document):\n\tpass\n")
    write(os.path.join(MOD_DIR, "doctype", "__init__.py"), "")
    write(os.path.join(MOD_DIR, "__init__.py"), "")
    build_workspace()


def build_workspace():
    ws = "thinkNXG E-Invoice Hub"
    shortcuts = [("Dashboard", "einvoice-hub-dashboard", "Green"),
                 ("Invoice Monitor", "Invoice Monitor", "Blue"),
                 ("Invoice Transactions", "Invoice Transaction", "Blue"),
                 ("Companies", "Company Integration Profile", "Green"),
                 ("ERP Connections", "ERP Connection", "Grey"),
                 ("ASP Connections", "ASP Connection", "Grey")]
    cards = {
        "Setup": ["Integration Tenant", "Company Integration Profile", "Mapping Configuration",
                  "E-Invoice Hub Settings"],
        "Connections": ["ERP Connection", "ASP Connection"],
        "ASP Management": ["UAE Accredited Service Provider", "ASP REST API Configuration", "Microvista Settings",
                           "ASP Provider"],
        "Catalogues": ["ERP Connector", "Compliance Profile"],
        "Monitoring": ["Invoice Transaction", "Integration Log", "Webhook Event", "Invoice Payload",
                       "Integration Audit Log"],
    }
    content = [{"id": "hdr1", "type": "header", "data": {"text": "<span class=\"h4\"><b>Shortcuts</b></span>", "col": 12}}]
    for i, (lbl, _, _) in enumerate(shortcuts):
        content.append({"id": f"sc{i}", "type": "shortcut", "data": {"shortcut_name": lbl, "col": 4 if len(shortcuts) % 4 else 3}})
    content.append({"id": "sp1", "type": "spacer", "data": {"col": 12}})
    content.append({"id": "hdr2", "type": "header", "data": {"text": "<span class=\"h4\"><b>Configuration and Monitoring</b></span>", "col": 12}})
    for i, card in enumerate(cards):
        content.append({"id": f"cd{i}", "type": "card", "data": {"card_name": card, "col": 3}})
    links = []
    for card, dts in cards.items():
        links.append({"hidden": 0, "is_query_report": 0, "label": card, "link_count": len(dts),
                      "link_type": "DocType", "onboard": 0, "type": "Card Break"})
        for dt in dts:
            links.append({"hidden": 0, "is_query_report": 0, "label": dt, "link_count": 0, "link_to": dt,
                          "link_type": "DocType", "onboard": 0, "type": "Link"})
    doc = {
        "charts": [], "content": json.dumps(content), "creation": TS, "custom_blocks": [], "docstatus": 0,
        "doctype": "Workspace", "for_user": "", "hide_custom": 0, "icon": "file", "idx": 0, "is_hidden": 0,
        "label": ws, "links": links, "modified": TS, "modified_by": "Administrator", "module": MODULE,
        "name": ws, "number_cards": [], "owner": "Administrator", "parent_page": "", "public": 1,
        "quick_lists": [], "roles": [], "sequence_id": 90.0,
        "shortcuts": [{"color": c, "label": l, "link_to": d,
                       **({"type": "Page"} if d == "einvoice-hub-dashboard" else
                          {"type": "Report"} if d == "Invoice Monitor" else {"type": "DocType", "doc_view": "List"})}
                      for l, d, c in shortcuts],
        "title": ws,
    }
    write(os.path.join(MOD_DIR, "workspace", scrub(ws), f"{scrub(ws)}.json"), json.dumps(doc, indent=1) + "\n")


if __name__ == "__main__":
    build()
    print(f"generated {len(DOCTYPES)} doctypes")
