"""Flick adapter: runs on an ASP REST API Configuration built from the provider's official API documentation."""

from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ContractPendingAdapter


class FlickAdapter(ContractPendingAdapter):
	code = "flick"
	label = "Flick"
	website = "https://www.flick.network/en"
	provider_name = "Flick"
	legal_name = "Flick Network L.L.C"
	accreditation_number = "138271"
	description = "Configuration-driven adapter. Not sandbox-tested; complete and verify the API configuration first."
