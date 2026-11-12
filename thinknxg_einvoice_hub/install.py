"""Install and migrate: roles and connector / provider / compliance catalogues."""

import frappe

ROLES = ("E-Invoice Hub Admin", "E-Invoice Hub Tenant Admin", "E-Invoice Hub User")


def before_install():
	create_roles()


def after_install():
	create_roles()
	sync_catalogues()
	sync_asp_directory()
	create_presets()


def after_migrate():
	create_roles()
	sync_catalogues()
	sync_asp_directory()
	create_presets()


def has_app_permission():
	roles = set(frappe.get_roles())
	return frappe.session.user == "Administrator" or bool(roles.intersection(ROLES + ("System Manager",)))


def create_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def _upsert(doctype, name, values):
	if frappe.db.exists(doctype, name):
		doc = frappe.get_doc(doctype, name)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def sync_catalogues():
	"""Mirror the code registries into catalogue records. Safe to run repeatedly."""
	from thinknxg_einvoice_hub.asp_connectors import base_adapter as asp
	from thinknxg_einvoice_hub.asp_connectors.adapter_registry import adapter_paths, get_adapter_class
	from thinknxg_einvoice_hub.compliance.registry import engine_paths, get_engine_class
	from thinknxg_einvoice_hub.erp_connectors import base_connector as erp
	from thinknxg_einvoice_hub.erp_connectors.connector_registry import connector_paths, get_connector_class

	for code, path in connector_paths().items():
		cls = get_connector_class(code)
		_upsert("ERP Connector", code, {
			"connector_name": cls.label or code,
			"connector_code": code,
			"status": cls.status,
			"integration_methods": cls.integration_methods,
			"connector_class": path,
			"description": cls.description,
			"supports_fetch_invoice": int(erp.CAP_FETCH_INVOICE in cls.capabilities),
			"supports_fetch_pending": int(erp.CAP_FETCH_PENDING in cls.capabilities),
			"supports_webhooks": int(erp.CAP_WEBHOOKS in cls.capabilities),
			"supports_purchase_invoice": int(erp.CAP_PURCHASE_INVOICE in cls.capabilities),
			"supports_status_update": int(erp.CAP_STATUS_UPDATE in cls.capabilities),
		})

	for code, path in adapter_paths().items():
		cls = get_adapter_class(code)
		_upsert("ASP Provider", code, {
			"provider_name": cls.label or code,
			"provider_code": code,
			"status": cls.status,
			"website": cls.website,
			"adapter_class": path,
			"description": cls.description,
			"supports_submit": int(asp.CAP_SUBMIT in cls.capabilities),
			"supports_status": int(asp.CAP_STATUS in cls.capabilities),
			"supports_inbound": int(asp.CAP_INBOUND in cls.capabilities),
			"supports_webhooks": int(asp.CAP_WEBHOOKS in cls.capabilities),
		})

	# compliance profiles are created once; administrators may then adjust identifiers
	for code in engine_paths():
		if frappe.db.exists("Compliance Profile", code):
			continue
		cls = get_engine_class(code)
		country = cls.country if cls.country and frappe.db.exists("Country", cls.country) else None
		frappe.get_doc({
			"doctype": "Compliance Profile",
			"profile_name": cls.label or code,
			"profile_code": code,
			"engine_code": code,
			"country": country,
			"standard": cls.standard,
			"spec_version": cls.spec_version,
			"enabled": 1,
			**cls.profile_defaults,
		}).insert(ignore_permissions=True)


# ---------------------------------------------------------------------- ASP directory and presets
#: asp_code -> integration facts for providers the hub knows something about. Everything else in the
#: Ministry of Finance directory is listed as accredited with integration "Not Started".
KNOWN_INTEGRATIONS = {
	"microvista": {"adapter": "microvista", "adapter_type": "Dedicated Adapter",
		"integration_status": "Skeleton - Pending API Documentation",
		"notes": "No public API documentation was found (searched 2026-11-12). Request the API reference and sandbox "
			"credentials from the provider; see docs/MICROVISTA_SETUP.md. Not production-ready."},
	"wafeq": {"adapter": "wafeq", "adapter_type": "Generic REST", "integration_status": "In Development",
		"api_documentation_url": "https://wafeq-e-invoicing-asp.readme.io/docs/getting-started",
		"sandbox_url": "https://api.wafeq.com/ae/v1", "production_url": "https://api.wafeq.com/ae/v1",
		"authentication_type": "API key (Authorization: Api-Key ...) or OAuth access token",
		"notes": "A configuration preset built from the public documentation is installed. It has never been run "
			"against the Wafeq sandbox."},
	"flick": {"adapter": "flick", "adapter_type": "Generic REST"},
	"marmin": {"adapter": "marmin", "adapter_type": "Generic REST"},
	"suntech": {"adapter": "suntech", "adapter_type": "Generic REST"},
	"fynamics": {"adapter": "fynamics", "adapter_type": "Generic REST"},
	"avalara": {"adapter": "avalara"}, "comarch": {"adapter": "comarch"}, "pagero": {"adapter": "pagero"},
	"cleartax": {"adapter": "cleartax"}, "cygnet": {"adapter": "cygnet"}, "edicom": {"adapter": "edicom"},
}
DIRECTORY_VERIFIED_ON = "2026-11-11"  # "Last updated" date printed on the Ministry of Finance page


def _slug(name):
	import re

	return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]


def read_asp_directory():
	import os

	path = os.path.join(os.path.dirname(__file__), "data", "uae_asp_directory.txt")
	rows = []
	with open(path, encoding="utf-8") as handle:
		for line in handle:
			line = line.strip()
			if not line or line.startswith("#"):
				continue
			parts = [p.strip() for p in line.split("|")]
			rows.append({"name": parts[0], "number": parts[1], "website": parts[2],
				"code": parts[3] if len(parts) > 3 and parts[3] else _slug(parts[0])})
	return rows


def sync_asp_directory():
	"""Create missing directory entries. Existing entries are never overwritten: administrators own them."""
	for row in read_asp_directory():
		if frappe.db.exists("UAE Accredited Service Provider", row["code"]):
			continue
		known = dict(KNOWN_INTEGRATIONS.get(row["code"]) or {})
		if known.get("adapter") and not frappe.db.exists("ASP Provider", known["adapter"]):
			known.pop("adapter")
		frappe.get_doc({
			"doctype": "UAE Accredited Service Provider",
			"asp_name": row["name"].split(" (")[0] if row["code"] in KNOWN_INTEGRATIONS else row["name"],
			"asp_code": row["code"],
			"legal_name": row["name"],
			"accreditation_number": row["number"],
			"official_website": "https://" + row["website"],
			"accreditation_status": "Accredited",
			"last_verification_date": DIRECTORY_VERIFIED_ON,
			"integration_status": "Not Started",
			"adapter_type": "None",
			"enabled": 1,
			**known,
		}).insert(ignore_permissions=True)


def create_presets():
	"""Install shared ASP REST API Configurations that were built from public provider documentation."""
	import json
	import os

	path = os.path.join(os.path.dirname(__file__), "asp_connectors", "uae", "wafeq", "preset.json")
	with open(path, encoding="utf-8") as handle:
		preset = json.load(handle)
	preset.pop("_source", None)
	code = preset["asp_code"]
	if frappe.db.exists("ASP REST API Configuration", {"asp_code": code, "tenant": ["is", "not set"]}):
		return
	if frappe.db.exists("UAE Accredited Service Provider", code):
		preset["accredited_provider"] = code
	doc = frappe.get_doc({"doctype": "ASP REST API Configuration", "enabled": 1, **preset})
	doc.insert(ignore_permissions=True)
	if preset.get("accredited_provider") and not frappe.db.get_value(
			"UAE Accredited Service Provider", code, "rest_configuration"):
		frappe.db.set_value("UAE Accredited Service Provider", code, "rest_configuration", doc.name)
