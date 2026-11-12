"""Payload construction for Microvista.

Until Microvista's request format is confirmed, two documented-by-configuration
routes exist and no field names are assumed here:

* the connection's Payload Format decides whether the PINT AE XML or the canonical
  JSON is sent as the request body, or
* request mapping rules in the ASP REST API Configuration build a provider-specific
  JSON body from the canonical invoice.

If Microvista requires something a mapping cannot express, implement it in
``build`` and keep it inside this package.
"""


def build(payload, metadata):
	"""Return the payload handed to the engine (unchanged by default)."""
	return payload
