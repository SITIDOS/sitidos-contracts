# CRM template namespace

These tables are a **template**, not a deployed namespace.

Per ADR-0005 D6 (forced revision): the canonical sitidos CRM is **Dataverse OData v4** read live via the
sitidos-native reader in `sitidos-data`. Tables here exist as the **schema contract** that the Dataverse
reader projects into when a workspace enables the `crm.dataverse` data source — and as the storage shape
for any future sitidos-native CRM (not currently planned).

When a workspace enables `crm.dataverse`:
1. The data source connector materializes a DuckDB view over Dataverse OData entities.
2. The view shape MUST match the columns declared here so MCP tools have a stable surface across
   workspaces that source CRM data from different providers (Dataverse today; Salesforce, HubSpot, etc.
   in future App Store catalog entries).
3. Watermarked-Dataverse columns (e.g. `_owninguser_value`) are projected to canonical names
   (`owner_user_external_id`) by the connector.

**Cryptoshred:** these tables are NEVER materialized for `crm.dataverse` (data lives upstream).
`cryptoshred.key_binding` is declared for future sitidos-native fallback only.

**Inheritance:** `permission_inheritance_contract='source_native_acl'` — Dataverse row-level security
projects through; no sitidos overlay (per D9b on-demand permission resolution).
