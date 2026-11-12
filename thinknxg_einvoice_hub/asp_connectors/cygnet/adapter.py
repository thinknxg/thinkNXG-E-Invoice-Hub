"""Cygnet adapter placeholder. See PlannedASPAdapter."""

from thinknxg_einvoice_hub.asp_connectors.base_adapter import PlannedASPAdapter


class CygnetAdapter(PlannedASPAdapter):
	code = "cygnet"
	label = "Cygnet"
	description = "Dedicated adapter pending provider API onboarding. Connect via the Generic REST adapter meanwhile."
