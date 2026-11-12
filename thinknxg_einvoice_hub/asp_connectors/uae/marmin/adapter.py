"""Marmin adapter: runs on an ASP REST API Configuration built from the provider's official API documentation."""

from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ContractPendingAdapter


class MarminAdapter(ContractPendingAdapter):
	code = "marmin"
	label = "Marmin"
	website = "https://www.marmin.ai"
	provider_name = "Marmin"
	legal_name = "Marmin AI Software Design LLC"
	accreditation_number = "160945"
	description = "Configuration-driven adapter. Not sandbox-tested; complete and verify the API configuration first."
