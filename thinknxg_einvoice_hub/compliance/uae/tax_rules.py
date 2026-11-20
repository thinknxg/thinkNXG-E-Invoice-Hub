"""UAE VAT category handling for PINT AE."""

from decimal import Decimal

from thinknxg_einvoice_hub.utils import issue, to_decimal

# canonical category -> PINT AE tax category code
CATEGORY_CODES = {
	"STANDARD": "S",
	"ZERO_RATED": "Z",
	"EXEMPT": "E",
	"OUT_OF_SCOPE": "O",
	"REVERSE_CHARGE": "AE",
	"MARGIN_SCHEME": "N",
}
CODE_CATEGORIES = {v: k for k, v in CATEGORY_CODES.items()}

STANDARD_RATE = Decimal("5")
ZERO_TAX_CATEGORIES = ("ZERO_RATED", "EXEMPT", "OUT_OF_SCOPE")
#: carry the 5% rate but no VAT on the document (buyer accounts for it / VAT inside the margin)
NO_TAX_CATEGORIES = ("REVERSE_CHARGE", "MARGIN_SCHEME")


def category_code(category):
	return CATEGORY_CODES.get(category)


def category_from_code(code):
	return CODE_CATEGORIES.get((code or "").upper())


def check_category(category, rate, tax_amount, reason, path):
	"""Category / rate / amount consistency for one line. Returns issue dicts.

	``reason`` is accepted for compatibility; exemption reason codes are checked by the validator.
	"""
	issues = []
	rate = to_decimal(rate, Decimal("0"))
	tax = to_decimal(tax_amount, Decimal("0"))
	if category not in CATEGORY_CODES:
		return [issue("Error", "EIH-AE-040", path, f"Tax category '{category}' is not valid for the UAE")]
	if category == "STANDARD":
		if rate <= 0:
			issues.append(issue("Error", "EIH-AE-041", path, "Standard-rated supplies need a tax rate above zero"))
		elif rate != STANDARD_RATE:
			issues.append(issue("Error", "EIH-AE-042", path,
				f"Standard rate is {rate}%; UAE VAT standard rate must be {STANDARD_RATE}% (ibr-190-ae)"))
	if category in ZERO_TAX_CATEGORIES and (rate != 0 or tax != 0):
		issues.append(issue("Error", "EIH-AE-043", path,
			f"{category} supplies must carry a zero tax rate and zero tax amount (ibr-165-ae)"))
	if category in NO_TAX_CATEGORIES:
		if rate <= 0:
			issues.append(issue("Error", "EIH-AE-041", path,
				f"{category} lines state the VAT rate (5%) (aligned-ibrp-ae-05-ae / ibr-111-ae)"))
		if tax != 0:
			issues.append(issue("Error", "EIH-AE-043", path,
				f"{category} lines must carry zero VAT on the document (ibr-162-ae / ibr-108-ae)"))
	return issues
