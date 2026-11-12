"""ERPNext / thinkNXG ERP connector (REST API + webhooks).

Authentication: API key and secret of an integration user (token auth).

Optional ``extra_config`` keys on the ERP Connection::

    {
      "tax_category_map": {"UAE VAT Zero - ABC": "ZERO_RATED", "UAE Exempt - ABC": "EXEMPT"},
      "zero_rate_category": "ZERO_RATED",     # category for 0% lines without a mapped template
      "default_country": "AE",
      "status_field": "custom_einvoice_status",       # custom fields (allow on submit) on Sales Invoice
      "reference_field": "custom_einvoice_reference",
      "company": "ABC Trading LLC",                   # company for inbound purchase invoices
      "default_supplier": "Unknown E-Invoice Supplier",
      "default_item": "E-Invoice Item",
      "use_source_item_codes": false,
      "purchase_taxes_template": "UAE VAT 5% - ABC"
    }
"""

import json
from html import escape
from urllib.parse import quote

from thinknxg_einvoice_hub.canonical.purchase_invoice_schema import to_purchase_view
from thinknxg_einvoice_hub.erp_connectors.base_connector import ALL_CAPABILITIES, BaseERPConnector
from thinknxg_einvoice_hub.exceptions import PermanentError


def _f(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


class ERPNextConnector(BaseERPConnector):
	code = "erpnext"
	label = "ERPNext / thinkNXG ERP"
	status = "Available"
	integration_methods = "REST API, Webhooks"
	description = "Sales Invoice retrieval, webhook intake, status write-back and draft Purchase Invoice creation."
	capabilities = frozenset(ALL_CAPABILITIES)

	# -- low level ---------------------------------------------------------
	def _resource(self, doctype, name=None):
		path = f"/api/resource/{quote(doctype)}"
		return f"{path}/{quote(str(name), safe='')}" if name else path

	def _get_doc(self, doctype, name):
		return self.http.json("GET", self._resource(doctype, name)).get("data") or {}

	def _list(self, doctype, filters, fields=("name",), limit=50, order_by="modified asc"):
		params = {
			"filters": json.dumps(filters),
			"fields": json.dumps(list(fields)),
			"limit_page_length": limit,
			"order_by": order_by,
		}
		return self.http.json("GET", self._resource(doctype), params=params).get("data") or []

	def authenticate(self):
		return self.http.json("GET", "/api/method/frappe.auth.get_logged_user").get("message")

	def test_connection(self):
		return f"Connected as {self.authenticate()}"

	# -- outbound ----------------------------------------------------------
	def _address(self, name):
		if not name:
			return None
		try:
			addr = self._get_doc("Address", name)
			code = None
			if addr.get("country"):
				code = (self._get_doc("Country", addr["country"]).get("code") or "").upper() or None
			return {
				"street": addr.get("address_line1"),
				"additional_street": addr.get("address_line2"),
				"city": addr.get("city"),
				"postal_code": addr.get("pincode"),
				"subdivision": addr.get("state"),
				"country": code,
			}
		except PermanentError:
			return None  # the integration user may not be allowed to read addresses

	def fetch_invoice(self, document_id):
		inv = self._get_doc("Sales Invoice", document_id)
		if not inv:
			raise PermanentError(f"Sales Invoice {document_id} not found")
		inv["_addresses"] = {
			"customer": self._address(inv.get("customer_address")),
			"company": self._address(inv.get("company_address")),
		}
		return inv

	def fetch_pending_invoices(self, filters=None):
		filters = dict(filters or {})
		limit = int(filters.pop("limit", 50))
		since = filters.pop("modified_after", None)
		conditions = [["docstatus", "=", 1]]
		if since:
			conditions.append(["modified", ">", str(since)])
		for field, value in filters.items():
			conditions.append([field, "=", value])
		return [row["name"] for row in self._list("Sales Invoice", conditions, limit=limit)]

	def _tax_category(self, item, rate):
		table = self.extra.get("tax_category_map") or {}
		template = item.get("item_tax_template")
		if template and template in table:
			return table[template]
		return "STANDARD" if rate > 0 else self.extra.get("zero_rate_category", "ZERO_RATED")

	def normalize_invoice(self, inv):
		if self.mapping and self.mapping.get("rules"):
			return super().normalize_invoice(inv)
		if "items" not in inv:
			return super().normalize_invoice(inv)

		is_return = bool(int(inv.get("is_return") or 0))
		default_rate = sum(_f(t.get("rate")) for t in inv.get("taxes") or [] if t.get("charge_type") == "On Net Total")
		lines = []
		for item in inv.get("items") or []:
			rate = default_rate
			try:
				per_item = json.loads(item.get("item_tax_rate") or "{}")
				if isinstance(per_item, dict) and per_item:
					rate = sum(_f(v) for v in per_item.values())
			except ValueError:
				pass
			net = abs(_f(item.get("net_amount") if item.get("net_amount") is not None else item.get("amount")))
			lines.append({
				"item_code": item.get("item_code"),
				"item_name": item.get("item_name"),
				"description": item.get("item_name") or item.get("description"),
				"quantity": abs(_f(item.get("qty"))),
				"unit_code": (self.extra.get("uom_map") or {}).get(item.get("uom")),
				"unit_price": abs(_f(item.get("net_rate") if item.get("net_rate") is not None else item.get("rate"))),
				"net_amount": net,
				"tax_category": self._tax_category(item, rate),
				"tax_rate": rate,
				"tax_amount": round(net * rate / 100, 2),
			})

		addresses = inv.get("_addresses") or {}
		default_country = self.extra.get("default_country", "AE")
		customer_addr = addresses.get("customer") or {}
		customer_addr["country"] = customer_addr.get("country") or default_country
		supplier_addr = addresses.get("company") or {}
		grand = abs(_f(inv.get("grand_total")))
		rounded = abs(_f(inv.get("rounded_total"))) or grand
		return {
			"schema_version": "1.0",
			"document": {
				"document_type": "CREDIT_NOTE" if is_return else "INVOICE",
				"invoice_kind": "TAX",
				"invoice_number": inv.get("name"),
				"invoice_date": inv.get("posting_date"),
				"due_date": inv.get("due_date"),
				"currency": inv.get("currency"),
				"exchange_rate": inv.get("conversion_rate") or 1,
				"direction": "OUTBOUND",
				"notes": inv.get("remarks") if inv.get("remarks") != "No Remarks" else None,
			},
			"supplier": {
				"legal_name": inv.get("company"),
				"tax_id": inv.get("company_tax_id"),
				"address": supplier_addr if supplier_addr.get("country") else {},
			},
			"customer": {
				"legal_name": inv.get("customer_name") or inv.get("customer"),
				"tax_id": inv.get("tax_id"),
				"address": customer_addr,
			},
			"lines": lines,
			"totals": {
				"subtotal": abs(_f(inv.get("net_total"))),
				"tax_total": abs(_f(inv.get("total_taxes_and_charges"))),
				"grand_total": grand,
				"rounding_amount": round(rounded - grand, 2),
				"payable_amount": rounded,
			},
			"payment": {"terms": inv.get("payment_terms_template")},
			"references": {
				"erp_name": "ERPNext",
				"erp_document_id": inv.get("name"),
				"order_reference": inv.get("po_no"),
				"original_invoice_number": inv.get("return_against"),
			},
		}

	def update_invoice_status(self, document_id, status, details=None):
		details = details or {}
		rows = "".join(f"<li>{escape(str(m.get('severity')))}: {escape(str(m.get('message')))}</li>" for m in details.get("messages") or [])
		content = (
			f"<b>thinkNXG E-Invoice Hub</b>: {escape(str(status))}"
			+ (f"<br>ASP reference: {escape(str(details.get('asp_reference')))}" if details.get("asp_reference") else "")
			+ (f"<br>{escape(str(details.get('message')))}" if details.get("message") else "")
			+ (f"<ul>{rows}</ul>" if rows else "")
		)
		self.http.json("POST", self._resource("Comment"), json={
			"comment_type": "Info",
			"reference_doctype": "Sales Invoice",
			"reference_name": document_id,
			"content": content,
		})
		update = {}
		if self.extra.get("status_field"):
			update[self.extra["status_field"]] = status
		if self.extra.get("reference_field") and details.get("asp_reference"):
			update[self.extra["reference_field"]] = details["asp_reference"]
		if update:
			self.http.json("PUT", self._resource("Sales Invoice", document_id), json=update)
		return True

	def parse_webhook(self, payload):
		payload = payload if isinstance(payload, dict) else {}
		if payload.get("doctype") not in (None, "Sales Invoice"):
			return {"event": "ignored", "document_id": None, "invoice": None}
		# the webhook body may carry only selected fields; always re-read the full document
		return {"event": "invoice.submitted", "document_id": payload.get("name"), "invoice": None}

	# -- inbound -----------------------------------------------------------
	def _find(self, doctype, filters):
		rows = self._list(doctype, filters, limit=1)
		return rows[0]["name"] if rows else None

	def create_purchase_invoice(self, invoice):
		view = to_purchase_view(invoice)
		supplier = None
		if view["supplier_tax_id"]:
			supplier = self._find("Supplier", [["tax_id", "=", view["supplier_tax_id"]]])
		supplier = supplier or self.extra.get("default_supplier")
		if not supplier:
			raise PermanentError(
				f"No Supplier with tax ID {view['supplier_tax_id']} in the ERP and no default_supplier configured"
			)
		default_item = self.extra.get("default_item")
		use_codes = bool(self.extra.get("use_source_item_codes"))
		sign = -1 if view["is_credit_note"] else 1
		items = []
		for line in view["lines"]:
			code = line["item_code"] if (use_codes and line["item_code"]) else default_item
			if not code:
				raise PermanentError("Configure default_item (or use_source_item_codes) on the ERP Connection")
			items.append({
				"item_code": code,
				"item_name": (line["item_name"] or code)[:140],
				"description": line["description"] or line["item_name"],
				"qty": sign * abs(_f(line["quantity"])),
				"rate": _f(line["unit_price"]),
			})
		doc = {
			"supplier": supplier,
			"bill_no": view["bill_no"],
			"bill_date": view["bill_date"],
			"posting_date": view["bill_date"],
			"set_posting_time": 1,
			"due_date": view["due_date"] or view["bill_date"],
			"currency": view["currency"],
			"items": items,
			"remarks": f"Received through thinkNXG E-Invoice Hub. Supplier TRN: {view['supplier_tax_id'] or '-'}",
		}
		if self.extra.get("company"):
			doc["company"] = self.extra["company"]
		if self.extra.get("purchase_taxes_template"):
			doc["taxes_and_charges"] = self.extra["purchase_taxes_template"]
		if view["is_credit_note"]:
			doc["is_return"] = 1
			if view["original_invoice_number"]:
				original = self._find("Purchase Invoice", [["bill_no", "=", view["original_invoice_number"]],
					["supplier", "=", supplier], ["docstatus", "=", 1]])
				if original:
					doc["return_against"] = original
		created = self.http.json("POST", self._resource("Purchase Invoice"), json=doc).get("data") or {}
		if not created.get("name"):
			raise PermanentError("ERP did not return the created Purchase Invoice")
		return created["name"]
