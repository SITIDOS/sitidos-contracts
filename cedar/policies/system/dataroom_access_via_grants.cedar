// dataroom_access_via_grants — Sitidos system-scope Cedar policy template.
//
// ADR-0006 D21 / D22 / Q2 / I12.
//
// Authorizes Data Room access by referencing pre-computed authorization sets
// loaded by F4's fact-builder injector. The fact-builder reads `dataroom.grants`
// rows matching the caller (workspace + principal + not-revoked + not-expired +
// mcp_access=true for MCP callers) and flattens them into three Cedar set
// attributes on the principal:
//
//   principal.dataroom_viewable_rooms      : Set<Sitidos::Dataroom::Room>
//   principal.dataroom_downloadable_rooms  : Set<Sitidos::Dataroom::Room>
//   principal.dataroom_manageable_rooms    : Set<Sitidos::Dataroom::Room>
//
// Inheritance is encoded by the fact-builder, not by Cedar:
//   - permission='manage'   → room appears in ALL THREE sets.
//   - permission='download' → room appears in viewable + downloadable.
//   - permission='view'     → room appears in viewable only.
//
// This shape uses only Cedar's standard `containsAny` and entity-`in`
// primitives — no custom builtins, no .filter() or .any() that vary across
// Cedar runtime versions. F4's fact-builder is the single source of truth for
// the flattening logic (I12: no independent re-derivation anywhere).
//
// I6 compliance: zero role-string literals. The only strings present are
// pre-computed-set ATTRIBUTE NAMES on the principal entity, populated by the
// fact-builder from dataroom.grants.permission column values.
//
// Workspace scoping: the fact-builder only injects rooms from the caller's
// workspace into these sets, so workspace equality is enforced at fact-build
// time. Each policy ALSO asserts `resource.workspace_id == principal.workspace_id`
// as defense-in-depth (a misconfigured fact graph can never authorize
// cross-workspace access).

// ─────────────────────────────────────────────────────────────────────────────
// Permit: view a document
//   Granted when the document's parent room is in the principal's viewable set.
// ─────────────────────────────────────────────────────────────────────────────
permit (
  principal,
  action == Sitidos::Action::"dataroom.document.view",
  resource is Sitidos::Dataroom::Document
)
when {
  principal.workspace_id == resource.workspace_id &&
  resource.room in principal.dataroom_viewable_rooms
};

// ─────────────────────────────────────────────────────────────────────────────
// Permit: download a document
//   Granted when the document's parent room is in the principal's downloadable
//   set. "view"-only grants are insufficient (preserves the watermarked-view
//   vs. raw-download distinction).
// ─────────────────────────────────────────────────────────────────────────────
permit (
  principal,
  action == Sitidos::Action::"dataroom.document.download",
  resource is Sitidos::Dataroom::Document
)
when {
  principal.workspace_id == resource.workspace_id &&
  resource.room in principal.dataroom_downloadable_rooms
};

// ─────────────────────────────────────────────────────────────────────────────
// Permit: manage a room (grant/revoke, edit room settings, delete room)
// ─────────────────────────────────────────────────────────────────────────────
permit (
  principal,
  action == Sitidos::Action::"dataroom.room.manage",
  resource is Sitidos::Dataroom::Room
)
when {
  principal.workspace_id == resource.workspace_id &&
  resource in principal.dataroom_manageable_rooms
};

// ─────────────────────────────────────────────────────────────────────────────
// Permit: list documents in a room
//   Required for `dataroom.documents.list` MCP tool + browser room view.
//   Threshold: any grant on the room (i.e. room in viewable set, since
//   viewable is the broadest set per inheritance).
// ─────────────────────────────────────────────────────────────────────────────
permit (
  principal,
  action == Sitidos::Action::"dataroom.documents.list",
  resource is Sitidos::Dataroom::Room
)
when {
  principal.workspace_id == resource.workspace_id &&
  resource in principal.dataroom_viewable_rooms
};

// ─────────────────────────────────────────────────────────────────────────────
// Permit: list rooms in a workspace
//   Required for `dataroom.rooms.list` MCP tool + browser room directory.
//   Resource = the workspace. Granted when the principal has at least one
//   viewable room.
//
//   The "at least one" check is enforced UPSTREAM by F4's fact-builder: it
//   only emits the `dataroom_viewable_rooms` attribute when the principal
//   holds ≥1 non-revoked, non-expired grant in this workspace. Cedar's
//   attribute-presence semantics mean that if the attribute is absent, the
//   `has` check below short-circuits to deny.
//
//   This places the burden of correctness on the fact-builder (single source
//   of truth per I12) and keeps the policy free of Cedar-version-specific
//   set-emptiness idioms.
// ─────────────────────────────────────────────────────────────────────────────
permit (
  principal,
  action == Sitidos::Action::"dataroom.rooms.list",
  resource is Sitidos::Workspace
)
when {
  principal.workspace_id == resource.id &&
  principal has dataroom_viewable_rooms
};
