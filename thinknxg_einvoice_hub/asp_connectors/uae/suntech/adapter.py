"""Suntech adapter: runs on an ASP REST API Configuration built from the provider's official API documentation."""

from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ContractPendingAdapter


class SuntechAdapter(ContractPendingAdapter):
	code = "suntech"
	label = "Suntech"
	website = "https://www.suntech-global.com"
	provider_name = "Suntech"
	legal_name = "Suntech Business Solutions DMCC"
	accreditation_number = "106799"
	description = "Configuration-driven adapter. Not sandbox-tested; complete and verify the API configuration first."
