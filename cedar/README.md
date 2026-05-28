# Cedar policies

Authoritative source for Sitidos Cedar authorization policies.

## Layout

- `policies/system/*.cedar` — system-scope templates shipped with Sitidos. Loaded into `acl.cedar_policies` (`scope_type='system'`) by F4's policy-loader at boot. Mirrored as seed fixtures under `iceberg/seeds/cedar_policies/`.
- `policies/org/*.cedar` (future) — org-scope policy authoring; not yet populated.
- `entities.json` (future) — Cedar entity schema declarations for compile-time validation.

## ADR-0006 templates

- `policies/system/dataroom_access_via_grants.cedar` — Data Room access via grants-derived principal attributes. Single template covers `view`, `download`, `manage`, `documents.list`, `rooms.list`. Per ADR-0006 D21 / D22 / Q2 / I12.

## Authoring rules

- **I6:** no Sitidos-native role string literals (e.g. `"admin"`, `"viewer"`). Policies parameterize over claim sets, grants, and pre-computed authorization sets only.
- **Defense-in-depth workspace scoping:** every policy must include `principal.workspace_id == resource.workspace_id` (or equivalent for workspace-typed resources). The fact-builder enforces workspace scoping at fact-build time; this is a belt-and-suspenders guard.
- **Cedar-version portability:** prefer standard set operations (`in`, `contains`, `has`) over runtime-specific builtins (`.filter()`, `.any()`, `.isEmpty()`).
- **Inheritance via fact-builder, not Cedar:** when a permission grade dominates another (e.g. `manage ⊇ download ⊇ view`), encode that in F4's fact-builder by inserting the same room into multiple sets — do NOT encode it as nested Cedar `||` expressions.
