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
REASON_CATEGORIES = ("EXEMPT", "OUT_OF_SCOPE", "REVERSE_CHARGE")


def category_code(category):
	return CATEGORY_CODES.get(category)


def category_from_code(code):
	return CODE_CATEGORIES.get((code or "").upper())


def check_category(category, rate, tax_amount, reason, path):
	"""Baseline category/rate consistency checks. Returns issue dicts."""
	issues = []
	rate = to_decimal(rate, Decimal("0"))
	tax = to_decimal(tax_amount, Decimal("0"))
	if category not in CATEGORY_CODES:
		return [issue("Error", "EIH-AE-040", path, f"Tax category '{category}' is not valid for the UAE")]
	if category == "STANDARD":
		if rate <= 0:
			issues.append(issue("Error", "EIH-AE-041", path, "Standard-rated supplies need a tax rate above zero"))
		elif rate != STANDARD_RATE:
			issues.append(issue("Warning", "EIH-AE-042", path,
				f"Standard rate is {rate}%, expected {STANDARD_RATE}% for UAE VAT"))
	if category in ZERO_TAX_CATEGORIES and (rate != 0 or tax != 0):
		issues.append(issue("Error", "EIH-AE-043", path,
			f"{category} supplies must carry a zero tax rate and zero tax amount"))
	if category in REASON_CATEGORIES and not reason:
		issues.append(issue("Warning", "EIH-AE-044", path,
			f"{category} supplies should state a tax exemption reason"))
	return issues
