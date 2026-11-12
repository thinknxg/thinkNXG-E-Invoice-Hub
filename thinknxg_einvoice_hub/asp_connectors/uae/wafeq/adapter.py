"""Wafeq adapter: runs on an ASP REST API Configuration built from the provider's official API documentation."""

from thinknxg_einvoice_hub.asp_connectors.generic_rest.configured import ContractPendingAdapter


class WafeqAdapter(ContractPendingAdapter):
	code = "wafeq"
	label = "Wafeq"
	website = "https://www.wafeq.com/en-ae"
	provider_name = "Wafeq"
	legal_name = "Wafeq FZ-LLC"
	accreditation_number = "129932"
	description = "Configuration-driven adapter. Not sandbox-tested; complete and verify the API configuration first."
