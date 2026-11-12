"""Roadmap connector placeholder(s). See PlannedERPConnector."""

from thinknxg_einvoice_hub.erp_connectors.base_connector import PlannedERPConnector


class OdooConnector(PlannedERPConnector):
	code = "odoo"
	label = "Odoo"
	integration_methods = "XML-RPC / JSON-RPC / REST"
	description = "Roadmap connector. Intended integration: XML-RPC / JSON-RPC / REST."
