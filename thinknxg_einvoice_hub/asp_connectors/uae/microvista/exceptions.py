from thinknxg_einvoice_hub.exceptions import NotSupportedError, PermanentError


class MicrovistaContractPending(NotSupportedError):
	"""The Microvista API contract has not been configured from official documentation yet."""


class MicrovistaError(PermanentError):
	"""Provider-side failure reported by Microvista."""
