"""Status handling for Microvista.

Microvista's status vocabulary is not public (checklist MV-08). Provider values are
translated by response-mapping rules (``map:{...}`` transformations); the three
outcomes stay separate: ASP acceptance, FTA reporting, Peppol delivery.
"""

# filled once the official status values are known, e.g. {"<provider value>": "ACCEPTED"}
SUBMISSION_STATUS_MAP = {}
FTA_STATUS_MAP = {}
DELIVERY_STATUS_MAP = {}
