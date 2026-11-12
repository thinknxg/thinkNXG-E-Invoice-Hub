"""ERP connector registry.

Built-in connectors are listed here. Additional connectors ship as separate
apps and register through the ``einvoice_hub_erp_connectors`` hook::

    # hooks.py of another app
    einvoice_hub_erp_connectors = {"netsuite": "my_app.connectors.NetSuiteConnector"}

Classes are only ever loaded from installed code (this map + hooks), never from
a path stored in the database.
"""

from thinknxg_einvoice_hub.exceptions import PermanentError
from thinknxg_einvoice_hub.utils import hook_map, load_class

_P = "thinknxg_einvoice_hub.erp_connectors"
BUILTIN_CONNECTORS = {
	"erpnext": f"{_P}.erpnext.connector.ERPNextConnector",
	"custom": f"{_P}.custom.connector.CustomERPConnector",
	"sap_s4hana": f"{_P}.sap.connector.SAPS4HanaConnector",
	"sap_b1": f"{_P}.sap.connector.SAPBusinessOneConnector",
	"oracle_fusion": f"{_P}.oracle.connector.OracleFusionConnector",
	"oracle_ebs": f"{_P}.oracle.connector.OracleEBSConnector",
	"odoo": f"{_P}.odoo.connector.OdooConnector",
	"zoho_books": f"{_P}.zoho.connector.ZohoBooksConnector",
	"focus": f"{_P}.focus.connector.FocusConnector",
	"dynamics": f"{_P}.dynamics.connector.DynamicsConnector",
	"tally": f"{_P}.tally.connector.TallyConnector",
}


def connector_paths():
	paths = dict(BUILTIN_CONNECTORS)
	paths.update(hook_map("einvoice_hub_erp_connectors"))
	return paths


def get_connector_class(code):
	path = connector_paths().get(code)
	if not path:
		raise PermanentError(f"No ERP connector registered for '{code}'")
	return load_class(path)


def get_connector(connection):
	"""Instantiate the connector for an ERP Connection (document or name)."""
	import frappe

	from thinknxg_einvoice_hub.core.connections import connection_config, mapping_config

	doc = frappe.get_doc("ERP Connection", connection) if isinstance(connection, str) else connection
	if not doc.enabled:
		raise PermanentError(f"ERP Connection {doc.name} is disabled")
	cls = get_connector_class(doc.erp_connector)
	return cls(connection_config(doc), mapping_config(doc.mapping_configuration))
