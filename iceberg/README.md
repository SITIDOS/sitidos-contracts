# Sitidos V2 — Iceberg Schemas

Authoritative schema definitions for every Iceberg table Sitidos manages, grouped by namespace.

**Source of truth.** Generated code (DuckDB DDL, Cedar fact templates, MCP tool contracts) must derive from these YAMLs, not the other way around. Schema PRs against this directory are the gating mechanism for any cross-vertical data shape change.

**Locked by ADR-0005** (`sitidos/sitidos` `docs/decisions/0005-pure-iceberg-everywhere.md`):

- D1 Iceberg-only persistence for Sitidos-managed data.
- D2 DuckDB-only query engine.
- D3 Apache Polaris as the Iceberg catalog.
- D4 Per-workspace OpenBao key as cryptoshred unit; per-entry `cryptoshred_coverage`.
- D9a/D9b per-connector role and permission inheritance contracts.
- D10 Literal fully-open App Store catalog.
- D13 Engine names never surface to end users.
- D14 No Sitidos-native role taxonomy.
- D15 Workspaces immutably bound to creating org.
- D17 Bootstrap admin transient state.
- D19 Every data source requires a `data_access_claim`.

## Namespace map

| Namespace | Purpose | Cryptoshred unit |
|---|---|---|
| `control.*` | Tenancy (orgs/workspaces/users/memberships), App Store catalogs and admin choices, gen cursors, ISR audit | Workspace key (for workspace-scoped rows); Org key (for org-scoped rows) |
| `identity.*` | Auth0 projection: users, connections, sessions, JWT metadata, claim snapshots | Workspace key (rows are workspace-scoped at projection time) |
| `esign.*` | Documenso fork tables, signature events, audit log | Workspace key |
| `acl.*` | Cedar fact store; inherited grants (roles + permissions) | Workspace key |
| `obs.*` | OTel events, traces, error groups | Workspace key (rows are workspace-scoped at ingest) |
| `dataroom.*` | V-DataRoom: rooms, documents, grants, watermark/download events | Workspace key |
| `crm/_template/*` | Materialized CRM mirror schema (instantiated per workspace as `crm.${workspace_id}.*`) | Workspace key |

## Schema YAML shape

Every table file declares:

```yaml
namespace: <namespace>
table: <table_name>
description: <one-line purpose>
partition_by: [<expr>, ...]      # Iceberg partition spec
sort_by: [<col>, ...]             # Iceberg sort order
schema:
  - { name: <col>, type: <type>, required: <bool>, doc: <str> }
properties:
  format-version: "2"
  write.format.default: parquet
  write.parquet.compression-codec: zstd
cryptoshred:
  key_binding: workspace | org | none
  key_ref_column: <col_name | null>
indexes_duckdb:                   # hint for DuckDB cache layer
  - { name: <idx>, columns: [<col>, ...], type: btree | hash | bloom }
foreign_keys:                     # informational only (Iceberg has no FK enforcement)
  - { columns: [<col>], references: <namespace.table>(<col>) }
```

## Layout

```
iceberg/
  README.md                      # this file
  control/
    orgs.yaml
    users.yaml
    workspaces.yaml
    org_memberships.yaml
    workspace_memberships.yaml          # materialized cache; derived from upstream claims
    org_identity_connections.yaml
    workspace_identity_connections_added.yaml
    workspace_identity_connections_opt_outs.yaml
    org_data_sources.yaml
    workspace_data_sources_added.yaml
    workspace_data_sources_opt_outs.yaml
    identity_connection_catalog.yaml    # dynamically refreshed by F19
    data_source_catalog.yaml            # dynamically refreshed by F19
    auth_provider_role_mappings.yaml    # upstream-claim → Sitidos concept maps (D14)
    gen_cursor.yaml                     # per-(entity_type, entity_id, namespace) monotonic
    revalidation_log.yaml               # ISR webhook receipts
    appstore_audit.yaml                 # enable/disable history
  identity/
    principals.yaml                     # 1:1 with control.users
    connections.yaml                    # Auth0 connection mirror
    sessions.yaml                       # Auth0 log-stream-derived
    tokens_metadata.yaml                # issued JWTs (no secret material)
    claim_snapshots.yaml                # per-session upstream claim snapshots for D9 evaluation
  esign/                                # batch 2
    ...
  acl/                                  # batch 2
    inherited_grants.yaml               # generalized: grant_kind in {role, permission}
    ...
  obs/                                  # batch 3
    ...
  dataroom/                             # batch 3
    ...
  crm/
    _template/                          # batch 3
      ...
```

## Batches

- **Batch 1 (this PR):** `control/*` + `identity/*` (17 tables).
- **Batch 2:** `esign/*` + `acl/*`.
- **Batch 3:** `obs/*` + `dataroom/*` + `crm/_template/*`.

## Cryptoshred binding rules

- `key_binding: workspace` → encrypted with the OpenBao key at `workspace/${workspace_id}/key`. Most rows.
- `key_binding: org` → encrypted with the org-level OpenBao key at `org/${org_id}/key`. Tenancy metadata above workspace scope (`orgs`, `org_memberships`, org-scoped catalog choices).
- `key_binding: none` → globally readable Sitidos metadata (catalogs, gen_cursor index rows). Never contains customer data.

## Naming conventions

- Table names: `snake_case`, singular for facts, plural for collections (`workspaces`, `org_memberships`).
- Column names: `snake_case`.
- Primary keys: `id` (string, ULID or UUID).
- Foreign keys: `${referenced_table_singular}_id`.
- Timestamps: `created_at`, `updated_at`, `deleted_at` (tombstone).
- Sources: `source` discriminator columns where rows can come from multiple connectors.
