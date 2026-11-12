"""Universal API / custom ERP connector.

Use this for any ERP that can call a REST API, post a webhook, or expose its
own REST endpoints. The ERP either pushes invoices to the hub (Universal API or
signed webhook), or the hub pulls them from endpoints configured below.
Payloads are canonical JSON, or any JSON mapped with a Mapping Configuration.

``extra_config`` keys (all optional)::

    {
      "invoice_path": "/invoices/{id}",            # GET one invoice
      "pending_path": "/invoices?status=pending",  # GET list of pending invoices
      "pending_list_path": "data",                 # where the array sits in the response
      "pending_id_field": "id",
      "status_path": "/invoices/{id}/einvoice-status",   # POST status updates
      "purchase_invoice_path": "/purchase-invoices",     # POST inbound invoices (canonical JSON)
      "purchase_invoice_id_path": "id",
      "test_path": "/health"
    }
"""

from thinknxg_einvoice_hub.erp_connectors.base_connector import ALL_CAPABILITIES, BaseERPConnector
from thinknxg_einvoice_hub.exceptions import NotSupportedError
from thinknxg_einvoice_hub.utils import get_path


class CustomERPConnector(BaseERPConnector):
	code = "custom"
	label = "Universal API / Custom ERP"
	status = "Available"
	integration_methods = "REST API, Webhooks, configurable field mapping"
	description = "Generic connector for any ERP with an API. Push invoices to the hub or let the hub pull them."
	capabilities = frozenset(ALL_CAPABILITIES)

	def _path(self, key, **fmt):
		template = self.extra.get(key)
		if not template:
			raise NotSupportedError(f"'{key}' is not configured on this ERP connection")
		return template.format(**fmt)

	def authenticate(self):
		return True

	def test_connection(self):
		if not self.extra.get("test_path"):
			return "No test_path configured; this connection works in push mode (Universal API / webhooks)"
		self.http.request("GET", self._path("test_path"))
		return "Connected"

	def fetch_invoice(self, document_id):
		return self.http.json("GET", self._path("invoice_path", id=document_id))

	def fetch_pending_invoices(self, filters=None):
		data = self.http.json("GET", self._path("pending_path"), params=filters or None)
		rows = get_path(data, self.extra.get("pending_list_path") or "data") if isinstance(data, dict) else data
		field = self.extra.get("pending_id_field") or "id"
		return [str(r.get(field)) if isinstance(r, dict) else str(r) for r in (rows or [])]

	def create_purchase_invoice(self, invoice):
		data = self.http.json("POST", self._path("purchase_invoice_path"), json=invoice)
		return str(get_path(data, self.extra.get("purchase_invoice_id_path") or "id") or "")

	def update_invoice_status(self, document_id, status, details=None):
		self.http.request("POST", self._path("status_path", id=document_id),
			json={"document_id": document_id, "status": status, **(details or {})})
		return True
