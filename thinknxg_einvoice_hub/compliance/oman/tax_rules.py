"""Oman VAT category handling for PINT OM (CL-04-OM, CL-05-OM, CL-10-OM).

Rates are effective-dated: ``standard_rate_schedule`` (engine settings, or the
Compliance Tax Rule rows of the Compliance Profile) lists ``(effective_from, rate)``
pairs. Ruleset 1.0.1 itself only accepts 5% for category S (ALIGNED-IBRP-S-05-OM).
"""

from decimal import Decimal

from thinknxg_einvoice_hub.compliance.oman import constants as C
from thinknxg_einvoice_hub.utils import issue, to_decimal, to_iso_date

ZERO = Decimal("0")
ZERO_TAX_CATEGORIES = ("ZERO_RATED", "EXEMPT", "OUT_OF_SCOPE")


class TaxRules:
	"""Category, rate and reason-code rules. All tables can be overridden from the engine profile."""

	def __init__(self, profile=None):
		profile = profile or {}
		self.category_codes = dict(profile.get("category_codes") or C.CATEGORY_CODES)
		self.code_categories = {v: k for k, v in self.category_codes.items()}
		self.exemption_codes = set(profile.get("exemption_codes") or C.EXEMPTION_CODES)
		self.zero_rating_codes = set(profile.get("zero_rating_codes") or C.ZERO_RATING_CODES)
		schedule = profile.get("standard_rate_schedule") or C.STANDARD_RATE_SCHEDULE
		self.schedule = sorted((str(d), Decimal(str(r))) for d, r in schedule)

	def code(self, category):
		return self.category_codes.get(category)

	def category(self, code):
		return self.code_categories.get((code or "").upper())

	def has_rate(self, category):
		return category not in C.NO_RATE_CATEGORIES

	def standard_rate(self, on_date=None):
		"""Standard VAT rate in force on ``on_date`` (ISO date); ``None`` before VAT existed."""
		on_date = to_iso_date(on_date) or self.schedule[-1][0]
		rate = None
		for start, value in self.schedule:
			if on_date >= start:
				rate = value
		return rate

	def check(self, category, rate, tax_amount, reason_code, path, on_date=None, simplified=False):
		"""Category / rate / reason-code consistency for one line, allowance/charge or breakdown row."""
		issues = []
		rate = to_decimal(rate, ZERO)
		tax = to_decimal(tax_amount, ZERO)
		if category not in self.category_codes:
			allowed = ", ".join(self.category_codes)
			return [issue("Error", "EIH-OM-040", path,
				f"Tax category '{category}' has no Oman VAT category (allowed: {allowed}; CL-04-OM). "
				"Reverse charge and profit margin are expressed through the transaction type")]
		reason_path = path.rsplit(".", 1)[0] + ".exemption_reason_code"
		if category == "STANDARD":
			expected = self.standard_rate(on_date)
			if expected is None:
				issues.append(issue("Error", "EIH-OM-041", path, "Oman VAT did not apply on the invoice date"))
			elif rate != expected:
				issues.append(issue("Error", "EIH-OM-042", path,
					f"Standard-rated supplies use {expected}% Oman VAT, not {rate}% (ALIGNED-IBRP-S-05-OM)"))
			if reason_code:
				issues.append(issue("Error", "EIH-OM-043", reason_path,
					"A standard-rated supply must not carry an exemption reason code (ALIGNED-IBRP-S-10-OM)"))
		if category in ZERO_TAX_CATEGORIES and not simplified and (rate != 0 or tax != 0):
			issues.append(issue("Error", "EIH-OM-044", path,
				f"{category} supplies must carry a zero VAT rate and zero VAT amount (IBR-077-OM, IBR-054-OM)"))
		if category == "EXEMPT":
			issues.extend(self._reason(reason_code, self.exemption_codes, "exemption", "CL-05-OM", "VATEX-OM-xx", reason_path))
		elif category == "ZERO_RATED":
			issues.extend(self._reason(reason_code, self.zero_rating_codes, "zero-rating", "CL-10-OM", "VATZR-OM-xx", reason_path))
		elif category == "OUT_OF_SCOPE" and reason_code:
			issues.append(issue("Error", "EIH-OM-047", reason_path,
				"An out-of-scope (O) supply must not carry an exemption reason code (IBR-070-OM)"))
		return issues

	def _reason(self, code, allowed, kind, rule, example, path):
		if not code:
			return [issue("Error", "EIH-OM-045", path, f"A {kind} reason code ({example}) is required (IBR-069-OM, {rule})")]
		if code not in allowed:
			return [issue("Error", "EIH-OM-046", path, f"'{code}' is not a {kind} reason code in {rule}")]
		return []
