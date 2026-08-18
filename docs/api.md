# API reference

The versioned HTTP contract is checked in as
[`api-openapi-v1.json`](api-openapi-v1.json). `GET` is the only API method;
`POST`, `PUT`, `PATCH`, and `DELETE` return `405 read_only`. The service emits
`Content-Type: application/json; charset=utf-8`, `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff`, and `X-API-Version: 1` on `/api/v1/*`.

`/api/*` is a compatibility alias for v1. Local and split-host clients use the
same `/api/v1` paths. Run and event responses are capped at 4 MiB; source files
are capped at 10 MiB and 10,000 events per run. Invalid run identifiers return
`400`, unknown runs return `404`, malformed sources return `503`, and oversized
responses return `413`. No endpoint writes, controls, or acknowledges a task.

The compatibility policy is additive within v1. A future v2 must be introduced
under `/api/v2`; aliases are not silently repointed.

The Python API pages are generated from source docstrings during the MkDocs build.

::: workbench.kernel.lifecycle

::: workbench.kernel.communication
