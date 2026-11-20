"""MOCK Oman accredited service provider, used only by the automated tests.

It imitates the behaviour the Oman Solution Architecture requires of a C2 access point,
not the API of any real provider:

* it accepts PINT OM XML only and recomputes the Invoice UUID (BTOM-002) from the
  document text the way C2 must (OM SRA 10.2.3); a mismatch is rejected
* it reports two independent outcomes through Peppol MLS codes: the invoice MLS from
  the buyer's provider (C3) and the TDD MLS from the Tax Authority's access point (C5)

Invoice-number markers drive the scenario:
  ``TDDRE``  -> Tax Data Document rejected (tdd_mls_code RE)
  ``C3RE``   -> buyer's provider rejects the invoice (invoice_mls_code RE)
  ``LATE``   -> MLS codes arrive only on a later status poll
  ``TIMEOUT`` -> the first submission fails temporarily (exercises retry), the next one succeeds
  B2C / export buyers (substitute participant IDs) -> no C3 delivery at all (OM SRA table 3)
"""

import xml.etree.ElementTree as ET

from thinknxg_einvoice_hub.asp_connectors.base_adapter import (
	ALL_CAPABILITIES,
	CAP_DELIVERY_STATUS,
	CAP_REPORTING_STATUS,
	ST_ACCEPTED,
	ST_REJECTED,
	BaseASPConnector,
	result,
)
from thinknxg_einvoice_hub.compliance.oman import constants as C
from thinknxg_einvoice_hub.compliance.oman import identifiers
from thinknxg_einvoice_hub.compliance.shared.xml import UBL_NS
from thinknxg_einvoice_hub.exceptions import PermanentError, TransientError

#: submitted documents by reference, shared across adapter instances within one test process
STORE = {}
FAILED_ONCE = set()


def recompute_uuid(xml):
	"""What an accredited provider computes from the received PINT OM document."""
	root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
	t = lambda path: (root.findtext(path, namespaces=UBL_NS) or "").strip()
	endpoint = root.find("cac:AccountingSupplierParty/cac:Party/cbc:EndpointID", UBL_NS)
	type_code = t("cbc:InvoiceTypeCode") or t("cbc:CreditNoteTypeCode")
	currency = t("cbc:DocumentCurrencyCode")
	tax_total = next((tt.findtext("cbc:TaxAmount", namespaces=UBL_NS) for tt in root.findall("cac:TaxTotal", UBL_NS)
		if tt.find("cbc:TaxAmount", UBL_NS).get("currencyID") == currency), None)
	flags = (root.find("cbc:InvoiceTypeCode", UBL_NS) if root.find("cbc:InvoiceTypeCode", UBL_NS) is not None
		else root.find("cbc:CreditNoteTypeCode", UBL_NS)).get("name") or ""
	pm = root.find("cac:AdditionalDocumentReference[cbc:DocumentTypeCode='PM_TOTAL']", UBL_NS)
	pm_total = pm.findtext("cbc:DocumentDescription", namespaces=UBL_NS) if pm is not None and (
		flags[9:10] == "1" or flags[10:11] == "1") else None
	return identifiers.invoice_uuid(endpoint.get("schemeID"), endpoint.text, type_code, t("cbc:ID"), t("cbc:IssueDate"),
		tax_total, t("cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"), pm_total)


class MockOmanProvider(BaseASPConnector):
	code = "mock_oman"
	label = "MOCK Oman provider (tests only)"
	status = "Planned"
	capabilities = frozenset(ALL_CAPABILITIES) | {CAP_REPORTING_STATUS, CAP_DELIVERY_STATUS}

	def authenticate(self):
		return True

	def test_connection(self):
		return "mock"

	def _outcome(self, doc):
		number = doc["number"].upper()
		out = {"tdd_mls_code": "RE" if "TDDRE" in number else "AP"}
		if doc["receiver"] not in C.SUBSTITUTE_PARTICIPANTS.values():
			out["invoice_mls_code"] = "RE" if "C3RE" in number else "AP"
		return out

	def submit_document(self, payload, metadata):
		if not isinstance(payload, str) or "urn:peppol:pint:" not in payload or "@om-1" not in payload:
			raise PermanentError("Mock Oman provider accepts PINT OM XML only")
		root = ET.fromstring(payload.encode())
		number = root.findtext("cbc:ID", namespaces=UBL_NS) or ""
		if "TIMEOUT" in number.upper() and number not in FAILED_ONCE:
			FAILED_ONCE.add(number)
			raise TransientError("Mock Oman provider: temporary failure")
		uuid = root.findtext("cbc:UUID", namespaces=UBL_NS)
		expected = recompute_uuid(payload)
		if uuid != expected:
			return result(ST_REJECTED, None, f"Invoice UUID {uuid} does not match the provider's computation {expected}",
				error_code="UUID_MISMATCH")
		receiver = root.findtext("cac:AccountingCustomerParty/cac:Party/cbc:EndpointID", namespaces=UBL_NS) or ""
		reference = f"MOCK-OM-{len(STORE) + 1:05d}"
		STORE[reference] = {"number": root.findtext("cbc:ID", namespaces=UBL_NS), "uuid": uuid, "receiver": receiver,
			"xml": payload, "metadata": {k: v for k, v in (metadata or {}).items() if k != "_canonical"}}
		extra = {} if "LATE" in STORE[reference]["number"].upper() else self._outcome(STORE[reference])
		return result(ST_ACCEPTED, reference, "Accepted by mock Oman provider", raw={"reference": reference},
			fta_status=None if extra else "PENDING", **extra)

	def get_document_status(self, reference):
		return self.get_reporting_status(reference)

	def get_reporting_status(self, reference):
		doc = STORE.get(reference)
		if not doc:
			raise PermanentError(f"Unknown reference {reference}")
		return result(ST_ACCEPTED, reference, "status", **self._outcome(doc))

	def get_delivery_status(self, reference):
		return self.get_reporting_status(reference)

	def receive_document(self, payload):
		return {"content": payload, "format": "XML"}

	def normalize_response(self, response):
		return response
