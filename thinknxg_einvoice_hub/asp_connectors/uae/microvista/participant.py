"""Participant lookup and registration for Microvista (checklist MV-03, MV-10)."""


def participant_id(tin, scheme="0235"):
	"""UAE Peppol participant identifier for a 10-digit TIN."""
	return f"{scheme}:{tin}" if tin else None
