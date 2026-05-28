# sitidos-contracts

Single source of truth for cross-repo contracts.

## Scope

- `openapi/rpc.yaml` — RPC HTTP API (sitidos-rpc surface, consumed by website + integrations)
- `mcp/tools/*.schema.json` — MCP tool schemas (sitidos-mcp publishes, agents consume)
- `cedar/policies/*.cedar` + `cedar/entities.json` — Cedar policy + entity schemas (compiled at admin-save time)
- `iceberg/tables/*.yaml` — Iceberg table contracts (column types, partitioning, sort order)
- `events/*.schema.json` — JSON-Schema for SSE events + Cloudflare Queues message envelopes
- `dataverse/entities.yaml` — emerging from Playwright specs; Dataverse entity definitions

## Versioning

SemVer per artifact. Breaking changes require bumping major + a `BREAKING_CHANGES.md` entry. Consumers pin via git submodule or npm `sitidos-contracts@1.2.3`.

## Owners

F9 (contract steward — reviews every PR for compat)
Every V-* vertical proposes changes via PR; F9 merges.
