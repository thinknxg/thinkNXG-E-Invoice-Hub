"""Roadmap connector placeholder(s). See PlannedERPConnector."""

from thinknxg_einvoice_hub.erp_connectors.base_connector import PlannedERPConnector


class OracleFusionConnector(PlannedERPConnector):
	code = "oracle_fusion"
	label = "Oracle Fusion"
	integration_methods = "REST APIs"
	description = "Roadmap connector. Intended integration: REST APIs."


class OracleEBSConnector(PlannedERPConnector):
	code = "oracle_ebs"
	label = "Oracle E-Business Suite"
	integration_methods = "REST / SOAP / interface tables"
	description = "Roadmap connector. Intended integration: REST / SOAP / interface tables."
