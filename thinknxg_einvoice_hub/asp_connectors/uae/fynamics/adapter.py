"""Fynamics adapter: runs on an ASP REST API Configuration built from the provider's official API documentation."""

from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ContractPendingAdapter


class FynamicsAdapter(ContractPendingAdapter):
	code = "fynamics"
	label = "Fynamics"
	website = "https://www.fynamicstax.com/uae"
	provider_name = "Fynamics"
	legal_name = "Fynamics Techno Solutions - FZCO"
	accreditation_number = "159905"
	description = "Configuration-driven adapter. Not sandbox-tested; complete and verify the API configuration first."
