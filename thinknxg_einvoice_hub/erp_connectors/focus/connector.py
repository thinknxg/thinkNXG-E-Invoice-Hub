"""Roadmap connector placeholder(s). See PlannedERPConnector."""

from thinknxg_einvoice_hub.erp_connectors.base_connector import PlannedERPConnector


class FocusConnector(PlannedERPConnector):
	code = "focus"
	label = "Focus ERP"
	integration_methods = "Available API / database / file integration"
	description = "Roadmap connector. Intended integration: Available API / database / file integration."
