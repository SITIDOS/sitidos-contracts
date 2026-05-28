#!/usr/bin/env python3
"""
ADR-0006 default-data-sources contract linter.

Enforces the three categories of rules introduced by ADR-0006:

  R1 (I10) — No `data_source_catalog` SEEDED row may declare
             permission_inheritance_contract='sitidos_native'. Default
             sources do not belong in the catalog. Operates on any seed
             fixtures under iceberg/seeds/data_source_catalog/ if present.

  R2       — `data_source_catalog.source_prefix` and
             `control.default_data_sources.source_prefix` namespaces are
             disjoint. Operates on seed fixtures under
             iceberg/seeds/{data_source_catalog,default_data_sources}/
             if present.

  R3       — Structural ADR-0006 invariants on the affected schemas:
             a) control.default_data_sources YAML exists with required
                columns (id, workspace_id, source_prefix, enabled_at,
                disabled_at, created_at, updated_at).
             b) dataroom.download_events YAML has `viewer_type` column
                with the three documented values in its doc string
                ('human_browser', 'mcp_client', 'rpc_api') and the
                'denied_mcp_access' outcome.
             c) dataroom.grants YAML has `mcp_access` boolean column.
             d) Every iceberg/**/*.yaml parses; has required top-level
                keys; cryptoshred.key_binding ∈ {workspace, org, none}.
             e) acl.cedar_policies description acknowledges the
                sitidos_native grants-entity carve-out (Q2/I12).
             f) dataroom.watermark_events description acknowledges
                viewer_type='human_browser' exclusivity (D24).

Exit code 0 = all rules pass. Non-zero = at least one rule failed; details
on stderr.

Usage:
  python3 scripts/lint_adr_0006.py            # lint everything under iceberg/
  python3 scripts/lint_adr_0006.py --strict   # treat R3-e/f description-only checks as errors

Without --strict, description-only checks (R3-e, R3-f) emit warnings on
stderr but do not fail the build, allowing description copy edits without
breaking CI. With --strict (default in CI), they fail.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ICEBERG = REPO_ROOT / "iceberg"
SEEDS = ICEBERG / "seeds"

REQUIRED_TOP_LEVEL = ["namespace", "table", "schema", "properties", "cryptoshred"]
ALLOWED_KEY_BINDING = {"workspace", "org", "none"}

# ADR-0006 R3-a expected columns on control.default_data_sources
DEFAULT_DATA_SOURCES_COLUMNS = {
    "id",
    "workspace_id",
    "source_prefix",
    "enabled_at",
    "disabled_at",
    "created_at",
    "updated_at",
}

# ADR-0006 R3-b expected viewer_type values (string-presence check in doc)
VIEWER_TYPE_VALUES = ["human_browser", "mcp_client", "rpc_api"]
DENIED_MCP_OUTCOME = "denied_mcp_access"

# ADR-0006 description-anchor strings (R3-e, R3-f)
CEDAR_DESCRIPTION_ANCHOR = "sitidos_native"
CEDAR_GRANTS_ANCHOR = "dataroom.grants"
WATERMARK_DESCRIPTION_ANCHOR = "human_browser"


class LintResult:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, rule: str, msg: str) -> None:
        self.errors.append(f"[{rule}] {msg}")

    def warn(self, rule: str, msg: str) -> None:
        self.warnings.append(f"[{rule}] {msg}")

    def ok(self) -> bool:
        return not self.errors


def load_yaml(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        with path.open() as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def lint_r3_structural(result: LintResult, strict: bool) -> None:
    """R3-d: every iceberg/**/*.yaml parses + has required keys + valid cryptoshred."""
    for yaml_path in sorted(ICEBERG.rglob("*.yaml")):
        # Skip seed fixtures (different schema — they are data rows, not table defs)
        if SEEDS in yaml_path.parents:
            continue
        rel = yaml_path.relative_to(REPO_ROOT)
        data = load_yaml(yaml_path)
        if data is None:
            result.err("R3-d", f"{rel}: empty file")
            continue
        if isinstance(data, dict) and "__parse_error__" in data:
            result.err("R3-d", f"{rel}: YAML parse error: {data['__parse_error__']}")
            continue
        if not isinstance(data, dict):
            result.err("R3-d", f"{rel}: top-level must be a mapping")
            continue
        for key in REQUIRED_TOP_LEVEL:
            if key not in data:
                result.err("R3-d", f"{rel}: missing required top-level key '{key}'")
        cs = data.get("cryptoshred", {})
        if not isinstance(cs, dict):
            result.err("R3-d", f"{rel}: cryptoshred must be a mapping")
        else:
            kb = cs.get("key_binding")
            if kb not in ALLOWED_KEY_BINDING:
                result.err(
                    "R3-d",
                    f"{rel}: cryptoshred.key_binding={kb!r} not in {sorted(ALLOWED_KEY_BINDING)}",
                )


def lint_r3a_default_data_sources(result: LintResult) -> None:
    path = ICEBERG / "control" / "default_data_sources.yaml"
    if not path.exists():
        result.err("R3-a", f"{path.relative_to(REPO_ROOT)}: required by ADR-0006 I9; file missing")
        return
    data = load_yaml(path) or {}
    if data.get("namespace") != "control" or data.get("table") != "default_data_sources":
        result.err("R3-a", f"{path.relative_to(REPO_ROOT)}: namespace/table mismatch")
    columns = {c.get("name") for c in (data.get("schema") or []) if isinstance(c, dict)}
    missing = DEFAULT_DATA_SOURCES_COLUMNS - columns
    if missing:
        result.err(
            "R3-a",
            f"{path.relative_to(REPO_ROOT)}: missing required columns: {sorted(missing)}",
        )
    cs = data.get("cryptoshred", {})
    if cs.get("key_binding") != "workspace":
        result.err(
            "R3-a",
            f"{path.relative_to(REPO_ROOT)}: cryptoshred.key_binding must be 'workspace' (D4)",
        )


def lint_r3b_download_events(result: LintResult) -> None:
    path = ICEBERG / "dataroom" / "download_events.yaml"
    if not path.exists():
        result.err("R3-b", f"{path.relative_to(REPO_ROOT)}: file missing")
        return
    data = load_yaml(path) or {}
    schema = data.get("schema") or []
    viewer_col = next(
        (c for c in schema if isinstance(c, dict) and c.get("name") == "viewer_type"),
        None,
    )
    if viewer_col is None:
        result.err(
            "R3-b",
            f"{path.relative_to(REPO_ROOT)}: missing 'viewer_type' column (ADR-0006 D24)",
        )
    else:
        if not viewer_col.get("required"):
            result.err(
                "R3-b",
                f"{path.relative_to(REPO_ROOT)}: 'viewer_type' must be required=true",
            )
        doc = viewer_col.get("doc") or ""
        for v in VIEWER_TYPE_VALUES:
            if v not in doc:
                result.err(
                    "R3-b",
                    f"{path.relative_to(REPO_ROOT)}: 'viewer_type' doc must enumerate {v!r}",
                )
    outcome_col = next(
        (c for c in schema if isinstance(c, dict) and c.get("name") == "outcome"),
        None,
    )
    if outcome_col is None:
        result.err(
            "R3-b",
            f"{path.relative_to(REPO_ROOT)}: missing 'outcome' column",
        )
    else:
        if DENIED_MCP_OUTCOME not in (outcome_col.get("doc") or ""):
            result.err(
                "R3-b",
                f"{path.relative_to(REPO_ROOT)}: 'outcome' doc must list {DENIED_MCP_OUTCOME!r} (ADR-0006 D24)",
            )


def lint_r3c_grants_mcp_access(result: LintResult) -> None:
    path = ICEBERG / "dataroom" / "grants.yaml"
    if not path.exists():
        result.err("R3-c", f"{path.relative_to(REPO_ROOT)}: file missing")
        return
    data = load_yaml(path) or {}
    schema = data.get("schema") or []
    col = next(
        (c for c in schema if isinstance(c, dict) and c.get("name") == "mcp_access"),
        None,
    )
    if col is None:
        result.err(
            "R3-c",
            f"{path.relative_to(REPO_ROOT)}: missing 'mcp_access' column (ADR-0006 Q1)",
        )
        return
    if col.get("type") != "boolean":
        result.err(
            "R3-c",
            f"{path.relative_to(REPO_ROOT)}: 'mcp_access' must be type=boolean (got {col.get('type')!r})",
        )
    if not col.get("required"):
        result.err(
            "R3-c",
            f"{path.relative_to(REPO_ROOT)}: 'mcp_access' must be required=true",
        )


def lint_r3e_cedar_description(result: LintResult, strict: bool) -> None:
    path = ICEBERG / "acl" / "cedar_policies.yaml"
    if not path.exists():
        result.err("R3-e", f"{path.relative_to(REPO_ROOT)}: file missing")
        return
    desc = (load_yaml(path) or {}).get("description") or ""
    missing_anchors = [
        a for a in (CEDAR_DESCRIPTION_ANCHOR, CEDAR_GRANTS_ANCHOR) if a not in desc
    ]
    if missing_anchors:
        msg = (
            f"{path.relative_to(REPO_ROOT)}: description missing ADR-0006 Q2/I12 "
            f"anchor(s): {missing_anchors}"
        )
        if strict:
            result.err("R3-e", msg)
        else:
            result.warn("R3-e", msg)


def lint_r3f_watermark_description(result: LintResult, strict: bool) -> None:
    path = ICEBERG / "dataroom" / "watermark_events.yaml"
    if not path.exists():
        result.err("R3-f", f"{path.relative_to(REPO_ROOT)}: file missing")
        return
    desc = (load_yaml(path) or {}).get("description") or ""
    if WATERMARK_DESCRIPTION_ANCHOR not in desc:
        msg = (
            f"{path.relative_to(REPO_ROOT)}: description missing ADR-0006 D24 anchor "
            f"({WATERMARK_DESCRIPTION_ANCHOR!r})"
        )
        if strict:
            result.err("R3-f", msg)
        else:
            result.warn("R3-f", msg)


def collect_seed_rows(subdir: str) -> list[dict[str, Any]]:
    seed_dir = SEEDS / subdir
    if not seed_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for yaml_path in sorted(seed_dir.rglob("*.yaml")):
        data = load_yaml(yaml_path)
        if isinstance(data, list):
            rows.extend(r for r in data if isinstance(r, dict))
        elif isinstance(data, dict):
            rows.append(data)
    return rows


def lint_r1_no_sitidos_native_in_catalog(result: LintResult) -> None:
    rows = collect_seed_rows("data_source_catalog")
    for row in rows:
        contract = row.get("permission_inheritance_contract")
        if contract == "sitidos_native":
            result.err(
                "R1",
                f"data_source_catalog seed row id={row.get('id')!r} "
                f"source_prefix={row.get('source_prefix')!r} has "
                f"permission_inheritance_contract='sitidos_native' (ADR-0006 I10 forbids)",
            )


def lint_r2_disjoint_source_prefix(result: LintResult) -> None:
    catalog_prefixes = {
        r.get("source_prefix")
        for r in collect_seed_rows("data_source_catalog")
        if r.get("source_prefix")
    }
    default_prefixes = {
        r.get("source_prefix")
        for r in collect_seed_rows("default_data_sources")
        if r.get("source_prefix")
    }
    overlap = catalog_prefixes & default_prefixes
    if overlap:
        result.err(
            "R2",
            f"source_prefix overlap between data_source_catalog and "
            f"control.default_data_sources seeds: {sorted(overlap)}",
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Treat description-only checks (R3-e, R3-f) as errors.",
    )
    args = ap.parse_args()

    result = LintResult()
    lint_r3_structural(result, strict=args.strict)
    lint_r3a_default_data_sources(result)
    lint_r3b_download_events(result)
    lint_r3c_grants_mcp_access(result)
    lint_r3e_cedar_description(result, strict=args.strict)
    lint_r3f_watermark_description(result, strict=args.strict)
    lint_r1_no_sitidos_native_in_catalog(result)
    lint_r2_disjoint_source_prefix(result)

    if result.warnings:
        print("ADR-0006 linter warnings:", file=sys.stderr)
        for w in result.warnings:
            print(f"  WARN {w}", file=sys.stderr)

    if result.errors:
        print("ADR-0006 linter errors:", file=sys.stderr)
        for e in result.errors:
            print(f"  FAIL {e}", file=sys.stderr)
        print(f"\n{len(result.errors)} error(s); {len(result.warnings)} warning(s).", file=sys.stderr)
        return 1

    print(f"ADR-0006 linter: OK ({len(result.warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
