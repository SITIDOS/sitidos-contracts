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

## CI

- `lint` workflow runs `scripts/lint_adr_0006.py --strict` on every PR and push to main. Enforces ADR-0006 structural invariants (default_data_sources existence, dataroom.grants.mcp_access column, dataroom.download_events viewer_type column, watermark/Cedar description anchors) and the R1/R2 seed-fixture rules (no `sitidos_native` in `data_source_catalog` seeds; disjoint `source_prefix` between catalog and defaults).

## Owners

F9 (contract steward — reviews every PR for compat)
Every V-* vertical proposes changes via PR; F9 merges.
