"""Roadmap connector placeholder(s). See PlannedERPConnector."""

from thinknxg_einvoice_hub.erp_connectors.base_connector import PlannedERPConnector


class DynamicsConnector(PlannedERPConnector):
	code = "dynamics"
	label = "Microsoft Dynamics"
	integration_methods = "REST / OData"
	description = "Roadmap connector. Intended integration: REST / OData."
