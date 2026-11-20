"""0.2.x -> 0.3.0: record the compliance country on existing profiles and transactions.

Only empty ``country_code`` values are filled, from each Compliance Profile's engine
(``uae_pint_ae`` -> AE). Nothing else on existing UAE transactions changes. The Oman
Compliance Profile itself is created by ``after_migrate`` (``install.sync_catalogues``).
Rollback: the field is additive; reverting the app leaves the column unused.
"""

import frappe

from thinknxg_einvoice_hub.compliance.registry import engine_paths, get_engine_class


def execute():
	codes = {}
	for code in engine_paths():
		try:
			codes[code] = get_engine_class(code).country_code or None
		except Exception:
			codes[code] = None
	for cp in frappe.get_all("Compliance Profile", fields=["name", "engine_code", "country_code"]):
		country = cp.country_code or codes.get(cp.engine_code)
		if country and not cp.country_code:
			frappe.db.set_value("Compliance Profile", cp.name, "country_code", country, update_modified=False)
		if country:
			table = frappe.qb.DocType("Invoice Transaction")
			(frappe.qb.update(table).set(table.country_code, country)
				.where(table.compliance_profile == cp.name)
				.where(table.country_code.isnull() | (table.country_code == ""))
				.run())
