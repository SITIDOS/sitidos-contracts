#!/usr/bin/env python3
"""
ADR-0007 Opus 4.8 + autonomy contract linter.

Enforces the seven categories of rules introduced by ADR-0007:

  R4 — Schema-shape invariants on the five new control tables:
       a) control/ai_model_law.yaml exists with required columns.
       b) control/ai_model_invocations.yaml exists with required columns.
       c) control/ai_irreversible_tools.yaml exists with required columns.
       d) control/workspace_ai_tool_policy.yaml exists with required columns.
       e) control/ai_run_cancellations.yaml exists with required columns.

  R5 — Irreversible-tool consistency. Any seed row in
       iceberg/seeds/workspace_ai_tool_policy/ that references a tool_id which
       ALSO appears as tool_id in iceberg/seeds/ai_irreversible_tools/ MUST NOT
       have policy='autonomous_allowed' (ADR-0007 I16).

  R6 — Every MCP tool definition (in iceberg/seeds/mcp_tools/ if present, or
       any future YAML declaring an MCP tool surface) MUST carry both
       'autonomy_safe' and 'irreversible' boolean fields (ADR-0007 I16).
       If no MCP tool seeds exist yet (empty registry), this rule passes.

  R7 — Every entry added under iceberg/seeds/mcp_tools/ MUST either:
       (a) appear in iceberg/seeds/ai_irreversible_tools/ (registered as
           hard-protected), OR
       (b) declare autonomy_safe=true AND include a non-empty
           autonomy_safe_justification field.
       Forces per-tool review for the default-autonomous + empty-registry
       day-one ship posture.

  R8 — Forbidden Anthropic SDK parameters in Sitidos AI code. Scans
       iceberg/, scripts/, and the repo root for any YAML/Python/TS file that
       names a forbidden param in a call to messages.create / Messages.create.
       Forbidden: temperature, top_p, top_k, thinking.budget_tokens. ADR-0007
       D36 / I20. (sitidos-contracts has no AI code today; this rule scans the
       repo defensively in case schema files declare default param values.)

  R9 — Required adaptive-thinking config. Any messages.create call in the
       repo MUST include thinking: {type: 'adaptive'} or equivalent. ADR-0007
       D35 / I21. (Defensive scan; main enforcement lives in service repos.)

  R10 — Required fast-mode flag. Any messages.create call in the repo MUST
        include speed: 'fast' unless the surrounding line contains the
        opt-out annotation 'sitidos-fast-mode-opt-out'. ADR-0007 D33 / I22.

Exit code 0 = all rules pass. Non-zero = at least one rule failed; details
on stderr.

Usage:
  python3 scripts/lint_adr_0007.py            # lint everything
  python3 scripts/lint_adr_0007.py --strict   # treat R9/R10 missing-scan as errors

R8/R9/R10 in this repo (contracts) are mostly defensive — there is no AI
client code here. They become load-bearing in sitidos / sitidos-mcp / sitidos-rpc.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ICEBERG = REPO_ROOT / "iceberg"
SEEDS = ICEBERG / "seeds"

# R4 required column sets per table
AI_MODEL_LAW_COLUMNS = {
    "id",
    "current_canonical_alias",
    "pinned_dated_id",
    "provider",
    "adr_ref",
    "effective_from",
    "fast_mode",
    "default_effort",
    "context_window_tokens",
    "max_output_tokens_default",
    "prompt_cache_min_tokens",
    "forbidden_sdk_params",
    "required_thinking_config",
    "default_max_tool_calls",
    "default_max_wall_time_sec",
    "default_max_tokens_per_run",
    "default_max_cost_usd_per_run",
    "default_max_sub_agent_depth",
    "default_max_sub_agent_fanout",
    "created_at",
    "updated_at",
}

AI_MODEL_INVOCATIONS_COLUMNS = {
    "id",
    "ts",
    "workspace_id",
    "org_id",
    "surface",
    "autonomy_level",
    "run_id",
    "parent_run_id",
    "cycle_index",
    "model_used",
    "model_pinned_id",
    "override_active",
    "effort_used",
    "fast_mode_used",
    "adaptive_thinking_triggered",
    "refusal_category",
    "prompt_tokens",
    "completion_tokens",
    "cache_hit_tokens",
    "cache_write_tokens",
    "latency_ms",
    "cost_usd",
    "request_id",
    "tool_calls_in_cycle",
    "tools_invoked",
    "stop_reason",
    "cancelled_at",
    "cancel_reason",
    "mid_conv_system_msgs_count",
    "created_at",
}

AI_IRREVERSIBLE_TOOLS_COLUMNS = {
    "tool_id",
    "namespace",
    "reason",
    "added_in_adr",
    "added_at",
    "added_by_user_id",
}

WORKSPACE_AI_TOOL_POLICY_COLUMNS = {
    "id",
    "workspace_id",
    "tool_id",
    "policy",
    "set_by_user_id",
    "set_at",
    "reason",
    "superseded_at",
    "created_at",
}

AI_RUN_CANCELLATIONS_COLUMNS = {
    "id",
    "run_id",
    "requested_at",
    "requested_by_user_id",
    "requested_by_scope",
    "reason",
    "acknowledged_at",
    "created_at",
}

# R8 forbidden params (D36 / I20)
FORBIDDEN_PARAMS = ["temperature", "top_p", "top_k", "thinking.budget_tokens"]

# Code-scan patterns
MESSAGES_CREATE_RE = re.compile(r"\b(?:messages|Messages)\.create\b")
OPT_OUT_MARKER = "sitidos-fast-mode-opt-out"

# Files to scan for R8/R9/R10 (code-style scan)
CODE_SCAN_GLOBS = ("**/*.py", "**/*.ts", "**/*.tsx", "**/*.js")


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


def load_yaml(path: pathlib.Path) -> Any:
    try:
        with path.open() as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def lint_r4_table_shape(
    result: LintResult,
    rule_id: str,
    rel_path: str,
    expected_columns: set[str],
    expected_namespace: str,
    expected_table: str,
) -> None:
    path = REPO_ROOT / rel_path
    if not path.exists():
        result.err(rule_id, f"{rel_path}: required by ADR-0007; file missing")
        return
    data = load_yaml(path) or {}
    if isinstance(data, dict) and "__parse_error__" in data:
        result.err(rule_id, f"{rel_path}: YAML parse error: {data['__parse_error__']}")
        return
    if data.get("namespace") != expected_namespace or data.get("table") != expected_table:
        result.err(
            rule_id,
            f"{rel_path}: namespace/table mismatch "
            f"(got {data.get('namespace')!r}/{data.get('table')!r}, "
            f"expected {expected_namespace!r}/{expected_table!r})",
        )
    columns = {c.get("name") for c in (data.get("schema") or []) if isinstance(c, dict)}
    missing = expected_columns - columns
    if missing:
        result.err(rule_id, f"{rel_path}: missing required columns: {sorted(missing)}")


def collect_seed_rows(subdir: str) -> list[dict[str, Any]]:
    seed_dir = SEEDS / subdir
    if not seed_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for yaml_path in sorted(seed_dir.rglob("*.yaml")):
        data = load_yaml(yaml_path)
        if isinstance(data, list):
            rows.extend(r for r in data if isinstance(r, dict))
        elif isinstance(data, dict) and "__parse_error__" not in data:
            rows.append(data)
    return rows


def lint_r5_irreversible_consistency(result: LintResult) -> None:
    """I16: workspace_ai_tool_policy MUST NOT have policy='autonomous_allowed' for any
    tool_id present in ai_irreversible_tools."""
    irreversible_ids = {
        r.get("tool_id")
        for r in collect_seed_rows("ai_irreversible_tools")
        if r.get("tool_id")
    }
    if not irreversible_ids:
        return  # Empty registry is the day-one ship state.
    for row in collect_seed_rows("workspace_ai_tool_policy"):
        if (
            row.get("tool_id") in irreversible_ids
            and row.get("policy") == "autonomous_allowed"
        ):
            result.err(
                "R5",
                f"workspace_ai_tool_policy seed row id={row.get('id')!r} "
                f"tool_id={row.get('tool_id')!r} has policy='autonomous_allowed' "
                f"but tool is in ai_irreversible_tools (ADR-0007 I16 forbids)",
            )


def lint_r6_r7_mcp_tools(result: LintResult) -> None:
    """R6: every MCP tool seed declares autonomy_safe + irreversible.
    R7: every MCP tool seed either appears in ai_irreversible_tools OR has
        autonomy_safe=true with non-empty autonomy_safe_justification."""
    tool_rows = collect_seed_rows("mcp_tools")
    if not tool_rows:
        return  # No MCP tool seeds yet; rules vacuously pass.
    irreversible_ids = {
        r.get("tool_id")
        for r in collect_seed_rows("ai_irreversible_tools")
        if r.get("tool_id")
    }
    for row in tool_rows:
        tid = row.get("tool_id") or row.get("id")
        if "autonomy_safe" not in row:
            result.err("R6", f"mcp_tools seed tool_id={tid!r}: missing autonomy_safe field")
        if "irreversible" not in row:
            result.err("R6", f"mcp_tools seed tool_id={tid!r}: missing irreversible field")
        # R7
        if tid in irreversible_ids:
            continue  # hard-protected; OK
        if row.get("autonomy_safe") is True and (row.get("autonomy_safe_justification") or "").strip():
            continue  # explicit justification; OK
        result.err(
            "R7",
            f"mcp_tools seed tool_id={tid!r}: not in ai_irreversible_tools AND "
            f"missing (autonomy_safe=true + non-empty autonomy_safe_justification). "
            f"ADR-0007 requires per-tool review.",
        )


def scan_code_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for glob in CODE_SCAN_GLOBS:
        files.extend(REPO_ROOT.rglob(glob))
    # Skip vendored / venv / node_modules, AND skip the linter scripts themselves
    # (they contain regex patterns matching the forbidden idioms — self-lint bootstrap).
    return [
        p
        for p in files
        if not any(part in {"node_modules", ".venv", "venv", "__pycache__", ".git"} for part in p.parts)
        and not (p.parent.name == "scripts" and p.name.startswith("lint_adr_"))
    ]


def lint_r8_forbidden_params(result: LintResult) -> None:
    """D36 / I20: scan code files for forbidden params in messages.create blocks."""
    files = scan_code_files()
    for path in files:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if not MESSAGES_CREATE_RE.search(text):
            continue
        # Crude scan: look for forbidden params anywhere in a file that contains
        # messages.create. Service repos should refine to AST-level checks.
        for param in FORBIDDEN_PARAMS:
            # match the param name as a property/identifier, not as a substring
            param_re = re.compile(rf"\b{re.escape(param.split('.')[0])}\b")
            if param_re.search(text):
                # Reduce false positives: require the param to appear within a
                # few lines of a messages.create occurrence.
                for m in MESSAGES_CREATE_RE.finditer(text):
                    window = text[max(0, m.start() - 500): m.end() + 500]
                    if param_re.search(window):
                        result.err(
                            "R8",
                            f"{path.relative_to(REPO_ROOT)}: forbidden param "
                            f"{param!r} near messages.create call (ADR-0007 D36/I20)",
                        )
                        break


def lint_r9_required_thinking(result: LintResult, strict: bool) -> None:
    """D35 / I21: messages.create MUST include thinking: {type: 'adaptive'}."""
    files = scan_code_files()
    for path in files:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for m in MESSAGES_CREATE_RE.finditer(text):
            window = text[max(0, m.start() - 200): m.end() + 800]
            has_thinking = re.search(
                r"thinking\s*[:=]\s*\{[^}]*type\s*[:=]\s*['\"]adaptive['\"]", window
            )
            if not has_thinking:
                msg = (
                    f"{path.relative_to(REPO_ROOT)}: messages.create at offset {m.start()} "
                    f"missing thinking: {{type: 'adaptive'}} (ADR-0007 D35/I21)"
                )
                if strict:
                    result.err("R9", msg)
                else:
                    result.warn("R9", msg)


def lint_r10_required_fast_mode(result: LintResult, strict: bool) -> None:
    """D33 / I22: messages.create MUST include speed: 'fast' unless opt-out marker."""
    files = scan_code_files()
    for path in files:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for m in MESSAGES_CREATE_RE.finditer(text):
            window = text[max(0, m.start() - 200): m.end() + 800]
            has_fast = re.search(r"speed\s*[:=]\s*['\"]fast['\"]", window)
            has_opt_out = OPT_OUT_MARKER in window
            if not has_fast and not has_opt_out:
                msg = (
                    f"{path.relative_to(REPO_ROOT)}: messages.create at offset {m.start()} "
                    f"missing speed: 'fast' (ADR-0007 D33/I22) and no "
                    f"'{OPT_OUT_MARKER}' annotation"
                )
                if strict:
                    result.err("R10", msg)
                else:
                    result.warn("R10", msg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Treat R9/R10 code-scan misses as errors (default: warnings).",
    )
    args = ap.parse_args()

    result = LintResult()

    # R4: schema-shape on the five new tables
    lint_r4_table_shape(
        result,
        "R4-a",
        "iceberg/control/ai_model_law.yaml",
        AI_MODEL_LAW_COLUMNS,
        "control",
        "ai_model_law",
    )
    lint_r4_table_shape(
        result,
        "R4-b",
        "iceberg/control/ai_model_invocations.yaml",
        AI_MODEL_INVOCATIONS_COLUMNS,
        "control",
        "ai_model_invocations",
    )
    lint_r4_table_shape(
        result,
        "R4-c",
        "iceberg/control/ai_irreversible_tools.yaml",
        AI_IRREVERSIBLE_TOOLS_COLUMNS,
        "control",
        "ai_irreversible_tools",
    )
    lint_r4_table_shape(
        result,
        "R4-d",
        "iceberg/control/workspace_ai_tool_policy.yaml",
        WORKSPACE_AI_TOOL_POLICY_COLUMNS,
        "control",
        "workspace_ai_tool_policy",
    )
    lint_r4_table_shape(
        result,
        "R4-e",
        "iceberg/control/ai_run_cancellations.yaml",
        AI_RUN_CANCELLATIONS_COLUMNS,
        "control",
        "ai_run_cancellations",
    )

    lint_r5_irreversible_consistency(result)
    lint_r6_r7_mcp_tools(result)
    lint_r8_forbidden_params(result)
    lint_r9_required_thinking(result, strict=args.strict)
    lint_r10_required_fast_mode(result, strict=args.strict)

    if result.warnings:
        print("ADR-0007 linter warnings:", file=sys.stderr)
        for w in result.warnings:
            print(f"  WARN {w}", file=sys.stderr)

    if result.errors:
        print("ADR-0007 linter errors:", file=sys.stderr)
        for e in result.errors:
            print(f"  FAIL {e}", file=sys.stderr)
        print(
            f"\n{len(result.errors)} error(s); {len(result.warnings)} warning(s).",
            file=sys.stderr,
        )
        return 1

    print(f"ADR-0007 linter: OK ({len(result.warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
