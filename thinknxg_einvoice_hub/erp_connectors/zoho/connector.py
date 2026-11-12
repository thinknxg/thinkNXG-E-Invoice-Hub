"""Roadmap connector placeholder(s). See PlannedERPConnector."""

from thinknxg_einvoice_hub.erp_connectors.base_connector import PlannedERPConnector


class ZohoBooksConnector(PlannedERPConnector):
	code = "zoho_books"
	label = "Zoho Books"
	integration_methods = "REST API / OAuth"
	description = "Roadmap connector. Intended integration: REST API / OAuth."
