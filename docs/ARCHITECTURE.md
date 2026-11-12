# Architecture

```
ERP / accounting system                                             UAE ASP
        |  push (Universal API, signed webhook)  or  pull (scheduler)   ^
        v                                                               |
  ERP connector            erp_connectors/<erp>/        (ERP-specific)  |
        v                                                               |
  Canonical invoice        canonical/                   (one model)     |
        v                                                               |
  UAE compliance engine    compliance/uae/              (validate, PINT AE UBL)
        v                                                               |
  Routing                  core/routing_engine.py       (company -> designated ASP)
        v                                                               |
  ASP adapter              asp_connectors/...           (provider-specific)
        v                                                               |
  Transport                services/asp_rest_engine.py  (auth, HTTP, retries, mapping) --+
        v
  Lifecycle                services/invoice_service.py  (ASP / FTA / delivery, idempotency)
```

## Layers and where provider or ERP specifics may live

| Layer | Code | May contain |
| --- | --- | --- |
| ERP normalisation | `erp_connectors/<erp>/`, Mapping Configuration | ERP field names, ERP API calls |
| Canonical model | `canonical/` | Nothing ERP- or ASP-specific |
| UAE compliance | `compliance/uae/` | PINT AE rules, code lists, UBL layout |
| ASP adapter | `asp_connectors/uae/<asp>/`, ASP REST API Configuration | Provider endpoints, payload shape, status vocabulary |
| Transport | `services/asp_rest_engine.py`, `http_client.py` | No provider or ERP knowledge |
| Lifecycle | `services/`, `core/` | No provider or ERP knowledge |

There is one processing workflow. Adding an ERP or an ASP never adds a workflow.

## Adapter types

* `sandbox` - simulated provider, transmits nothing.
* `rest_config` - runs an ASP REST API Configuration created in the UI. Capabilities follow the
  operations that are configured.
* Dedicated adapters (`microvista`, `wafeq`, `flick`, `marmin`, `suntech`, `fynamics`) - subclasses of
  the configurable adapter. They refuse to run until a contract is configured and can override
  anything unusual about the provider.
* `generic_rest` - the earlier JSON-options adapter, kept for backward compatibility.
* Placeholders (`comarch`, `pagero`, `avalara`, `cleartax`, `cygnet`, `edicom`).

## Lifecycle

Overall status: Received, Normalized, Validated, Validation Failed, Submitted, Delivered, Rejected,
Retrying, Failed, Duplicate, Cancelled.

Four outcomes are stored separately and only move forward:

| Field | Values |
| --- | --- |
| Internal Validation | Pending, Passed, Failed |
| ASP Submission | Not Submitted, Queued, Submitted, Accepted, Rejected |
| FTA Reporting | Not Applicable, Pending, Reported, Rejected |
| Peppol Delivery | Not Applicable, Pending, Delivered, Failed |

ERP synchronisation has its own field (Not Applicable, Pending, Synced, Failed). ASP acceptance never
implies FTA reporting or delivery: those are set only when the provider reports them.

The brief's longer status list (for example "FTA Pending", "Delivery Pending") is expressed as
combinations of these fields rather than as extra overall statuses, so existing integrations that
read the overall status keep working.

## Idempotency

* Same ERP document ID on the same connection returns the existing transaction.
* Same invoice number for the same company becomes `Duplicate`.
* A transaction is processed by one worker at a time (cache lock).
* The provider document ID is committed as soon as it is received; a transaction that has one is
  never submitted again, only polled.
* The transaction ID is sent as the idempotency key on every attempt when the endpoint enables it.
* A POST is retried inside the engine only when the endpoint has idempotency enabled.
* Webhook events are de-duplicated by provider event ID (or body hash).

## Security

* Tenant isolation on lists, documents and API; shared (tenant-less) REST configurations are
  read-only for tenants.
* Secrets in encrypted password fields, decrypted only in `core/connections.py`, masked in logs and
  error messages; access tokens live in the site cache only.
* Outbound calls: HTTPS only, approved hosts only, no private addresses, no redirects, timeouts,
  response-size limit. Two settings relax this for on-premise or test use.
* Mapping transformations come from a fixed whitelist plus functions registered in installed code;
  nothing from a configuration is evaluated or imported.
* Webhooks: per-connection endpoint, signature required, body not stored when verification fails,
  rate limited.
