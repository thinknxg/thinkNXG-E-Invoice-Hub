"""Country compliance engine contract.

A compliance engine turns a canonical invoice into the document a network or
tax authority expects, and back again for inbound documents. Engines are pure
Python: they receive a plain ``profile`` dict and never touch the database.
"""

from abc import ABC, abstractmethod


class BaseComplianceEngine(ABC):
	code = ""
	label = ""
	country = ""
	standard = ""
	spec_version = ""
	document_format = "XML"
	#: seed values for the Compliance Profile record created at install
	profile_defaults = {}

	def __init__(self, profile=None):
		self.profile = dict(self.profile_defaults)
		self.profile.update({k: v for k, v in (profile or {}).items() if v not in (None, "")})

	def enrich(self, invoice):
		"""Derive country-specific identifiers (e.g. participant IDs). Returns the invoice."""
		return invoice

	@abstractmethod
	def validate(self, invoice):
		"""Return a list of issue dicts (severity, rule_id, field_path, message)."""

	@abstractmethod
	def generate_document(self, invoice):
		"""Return ``{"content": str, "format": "XML"|"JSON", "media_type": str}``."""

	@abstractmethod
	def parse_document(self, content):
		"""Parse a received compliance document into a canonical invoice."""

	def participant_id(self, party):
		"""Network address of a party, e.g. ``0235:1000000000``; ``None`` when unknown."""
		return None
