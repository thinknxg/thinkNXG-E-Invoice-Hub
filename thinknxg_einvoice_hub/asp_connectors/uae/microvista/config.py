"""Static facts about the provider and the list of contract details still to be obtained."""

PROVIDER_CODE = "microvista"
PROVIDER_NAME = "Microvista"
LEGAL_NAME = "Microvista Technologies LLC"
# Ministry of Finance list of eInvoicing Accredited Service Providers (checked 2026-11-12)
ACCREDITATION_NUMBER = "157529"
WEBSITE = "https://www.microvistatech.com/e-invoicing-in-uae"
ONBOARDING_CONTACT = "uaesales@microvistatech.com"
INTEGRATION_STATUS = "Skeleton - Pending API Documentation"

# operations the hub needs before Microvista can carry live traffic
REQUIRED_OPERATIONS = ("Submit Invoice", "Get Invoice Status")
RECOMMENDED_OPERATIONS = ("Verify Credentials", "Submit Credit Note", "Validate Invoice", "Get Reporting Status",
	"Get Delivery Status", "Download XML", "Download PDF", "Get Participant", "Get Incoming Invoices",
	"Register Webhook")

# (id, what must be confirmed from Microvista's official documentation, where it is configured)
API_CHECKLIST = (
	("MV-01", "Sandbox and production base URLs", "ASP REST API Configuration > Sandbox / Production Base URL"),
	("MV-02", "Authentication scheme, credential names, token endpoint and token lifetime", "Authentication section"),
	("MV-03", "How the taxpayer / participant is identified on each call (header, path or body)", "Headers / endpoint URLs"),
	("MV-04", "Invoice submission endpoint, method and accepted payload (PINT AE XML, JSON or both)", "Endpoint 'Submit Invoice' + request mapping"),
	("MV-05", "Credit note and self-billed document submission (same or separate endpoints)", "Endpoints 'Submit Credit Note' / 'Submit Self-Billed Invoice'"),
	("MV-06", "Pre-submission validation endpoint, if offered", "Endpoint 'Validate Invoice'"),
	("MV-07", "Submission response: document ID field, status values, error structure", "Response mapping"),
	("MV-08", "Status endpoint(s): ASP status, FTA reporting status and Peppol delivery status values", "Endpoints 'Get Invoice Status' / 'Get Reporting Status' / 'Get Delivery Status' + response mapping"),
	("MV-09", "XML and PDF retrieval endpoints and response type (binary or download link, link host)", "Endpoints 'Download XML' / 'Download PDF', Approved Hosts"),
	("MV-10", "Participant lookup / registration endpoints", "Endpoints 'Get Participant' / 'Register Participant'"),
	("MV-11", "Incoming invoice retrieval (polling endpoint and/or webhook event)", "Endpoint 'Get Incoming Invoices' / webhook configuration"),
	("MV-12", "Webhook registration, event names, payload shape, signature header and algorithm, retry policy", "Webhook configuration"),
	("MV-13", "Idempotency mechanism (header or body field) and duplicate-submission behaviour", "Endpoint idempotency settings"),
	("MV-14", "Rate limits, timeouts and maximum payload size", "Endpoint timeout / retry settings"),
	("MV-15", "Sandbox credentials and official sample requests and responses for fixtures", "tests/ (replace the mock fixtures)"),
)
