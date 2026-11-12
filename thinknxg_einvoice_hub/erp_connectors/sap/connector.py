"""Roadmap connector placeholder(s). See PlannedERPConnector."""

from thinknxg_einvoice_hub.erp_connectors.base_connector import PlannedERPConnector


class SAPS4HanaConnector(PlannedERPConnector):
	code = "sap_s4hana"
	label = "SAP S/4HANA"
	integration_methods = "REST / OData / IDoc"
	description = "Roadmap connector. Intended integration: REST / OData / IDoc."


class SAPBusinessOneConnector(PlannedERPConnector):
	code = "sap_b1"
	label = "SAP Business One"
	integration_methods = "Service Layer"
	description = "Roadmap connector. Intended integration: Service Layer."
