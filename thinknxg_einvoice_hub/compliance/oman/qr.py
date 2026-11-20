"""Oman QR code payload: Base64 of Tag-Length-Value fields [OM-SRA 4.2, Appendix D.2].

The seller prints this QR code on the human-readable invoice it gives a consumer
(B2C full / simplified) or on a profit-margin invoice. The hub produces the
Base64 text; rendering the QR image is left to the ERP's print format.

Tags, B2C full / simplified (invoice type ``01``):
  1 QR version, 2 invoice type, 3 invoice number, 4 seller name, 5 seller VATIN,
  6 date, 7 time, 8 total with VAT, 9 VAT total, 10 Seller UUID
Tags, profit margin (invoice type ``02``):
  1..7 as above, 8 total amount due (BTOM-020), 9 Seller UUID
"""

import base64

from thinknxg_einvoice_hub.compliance.oman import constants as C
from thinknxg_einvoice_hub.compliance.oman import identifiers
from thinknxg_einvoice_hub.exceptions import PermanentError


def tlv(tag, value):
	data = str(value).encode("utf-8")
	if len(data) > 255:
		raise PermanentError(f"QR field {tag} is longer than 255 bytes")
	return bytes((tag, len(data))) + data


def fields(number, seller_name, vatin, issue_date, issue_time, total, vat_total=None, profit_margin=False,
		seller_uuid=None, qr_version=C.QR_VERSION):
	"""Ordered (tag, value) pairs; computes the Seller UUID when not given."""
	inv_type = C.QR_INVOICE_TYPES["PROFIT_MARGIN" if profit_margin else "STANDARD"]
	seller_uuid = seller_uuid or identifiers.seller_uuid(inv_type, number, seller_name, vatin, issue_date,
		issue_time, total, vat_total, qr_version=qr_version)
	values = [qr_version, inv_type, number, seller_name, vatin, issue_date, issue_time, total]
	if not profit_margin:
		values.append(vat_total)
	values.append(seller_uuid)
	return [(i + 1, v) for i, v in enumerate(values)]


def encode(pairs):
	"""Base64 text for the QR code; refuses payloads over the 700-character limit."""
	text = base64.b64encode(b"".join(tlv(tag, value) for tag, value in pairs)).decode("ascii")
	if len(text) > C.QR_MAX_BASE64:
		raise PermanentError(f"Oman QR payload is {len(text)} characters; the limit is {C.QR_MAX_BASE64}")
	return text


def decode(text):
	raw = base64.b64decode(text)
	out, i = [], 0
	while i < len(raw):
		tag, length = raw[i], raw[i + 1]
		out.append((tag, raw[i + 2:i + 2 + length].decode("utf-8")))
		i += 2 + length
	return out
