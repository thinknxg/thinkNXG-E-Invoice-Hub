"""Flat purchase-invoice view of an inbound canonical invoice.

ERP connectors use this when creating a draft purchase invoice so that each
connector does not need to re-derive the same fields from the canonical model.
"""

from thinknxg_einvoice_hub.canonical.credit_note_schema import is_credit_note
from thinknxg_einvoice_hub.utils import get_path


def to_purchase_view(inv):
	return {
		"is_credit_note": is_credit_note(inv),
		"supplier_name": get_path(inv, "supplier.legal_name"),
		"supplier_tax_id": get_path(inv, "supplier.tax_id"),
		"buyer_tax_id": get_path(inv, "customer.tax_id"),
		"bill_no": get_path(inv, "document.invoice_number"),
		"bill_date": get_path(inv, "document.invoice_date"),
		"due_date": get_path(inv, "document.due_date"),
		"currency": get_path(inv, "document.currency"),
		"exchange_rate": get_path(inv, "document.exchange_rate") or 1,
		"original_invoice_number": get_path(inv, "references.original_invoice_number"),
		"order_reference": get_path(inv, "references.order_reference"),
		"notes": get_path(inv, "document.notes"),
		"lines": [
			{
				"item_code": line.get("item_code"),
				"item_name": line.get("item_name") or line.get("description"),
				"description": line.get("description") or line.get("item_name"),
				"quantity": line.get("quantity"),
				"unit_code": line.get("unit_code"),
				"unit_price": line.get("unit_price"),
				"net_amount": line.get("net_amount"),
				"tax_category": line.get("tax_category"),
				"tax_rate": line.get("tax_rate"),
				"tax_amount": line.get("tax_amount"),
			}
			for line in inv.get("lines") or []
		],
		"subtotal": get_path(inv, "totals.subtotal"),
		"tax_total": get_path(inv, "totals.tax_total"),
		"grand_total": get_path(inv, "totals.grand_total"),
	}
