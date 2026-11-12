"""Exception hierarchy shared by connectors, engines and services.

The retry engine only re-queues work that failed with a ``TransientError``.
"""


class HubError(Exception):
	retryable = False


class TransientError(HubError):
	"""Temporary failure (timeout, HTTP 5xx, rate limit). Safe to retry."""

	retryable = True


class PermanentError(HubError):
	"""Failure that will not succeed on retry (bad credentials, rejected payload)."""


class NotSupportedError(PermanentError):
	"""The connector does not advertise the requested capability."""


class MappingError(PermanentError):
	"""ERP payload could not be mapped to the canonical invoice."""
