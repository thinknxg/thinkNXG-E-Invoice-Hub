"""Roadmap connector placeholder(s). See PlannedERPConnector."""

from thinknxg_einvoice_hub.erp_connectors.base_connector import PlannedERPConnector


class TallyConnector(PlannedERPConnector):
	code = "tally"
	label = "Tally"
	integration_methods = "Tally XML / HTTP"
	description = "Roadmap connector. Intended integration: Tally XML / HTTP."
