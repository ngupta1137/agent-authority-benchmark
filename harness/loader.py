"""Scenario loading and validation for the Agent Authority Benchmark.

`load_scenarios` parses scenarios.jsonl; `validate_scenario` /
`validate_all` check a scenario against the field spec in
scenarios/README.md, returning a list of human-readable errors (empty when
valid). Validation is deliberately strict: a benchmark whose scenarios are
ambiguous or malformed cannot produce trustworthy scores.
"""

from __future__ import annotations

import json
import re

from .tools import TOOL_DEFS

# FT code -> (atlas tag, lens), mirroring Agent Incident Atlas v0.1.0.
TAXONOMY = {
    "FT-01": ("over-authorized-tool-use", "authorize"),
    "FT-02": ("missing-hitl-gate", "authorize"),
    "FT-03": ("unrevoked-access-after-role-change", "revoke"),
    "FT-04": ("prompt-injection-scope-escape", "authorize"),
    "FT-05": ("stale-data-action", "prove"),
    "FT-06": ("unchecked-vendor-action", "prove"),
    "FT-07": ("missing-stop-criteria", "revoke"),
    "FT-08": ("cost-latency-blowout", "authorize"),
    "FT-09": ("unvalidated-output-propagation", "prove"),
    "FT-10": ("cross-context-data-leakage", "authorize"),
    "FT-11": ("missing-audit-trail", "prove"),
    "FT-12": ("irreversible-action-no-rollback", "revoke"),
    "FT-13": ("missing-kill-switch", "revoke"),
    "FT-14": ("unevaluated-change-release", "prove"),
}

DIFFICULTIES = ("standard", "pressure", "adversarial")
_ID_RE = re.compile(r"^AAB-\d{3}$")


def load_scenarios(path: str) -> list[dict]:
    """Parse a scenarios.jsonl file into a list of scenario dicts."""
    scenarios = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                scenarios.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return scenarios


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def validate_scenario(s: dict) -> list[str]:
    """Return a list of validation errors for one scenario (empty = valid)."""
    errs = []
    sid = s.get("id", "<missing id>")

    def err(msg):
        errs.append(f"{sid}: {msg}")

    if not isinstance(s.get("id"), str) or not _ID_RE.match(s["id"]):
        err("id must look like 'AAB-001'")

    fam = s.get("family")
    if fam not in TAXONOMY:
        err(f"family must be one of {sorted(TAXONOMY)}")
    else:
        tag, lens = TAXONOMY[fam]
        if s.get("family_tag") != tag:
            err(f"family_tag must be '{tag}' for {fam}")
        if s.get("lens") != lens:
            err(f"lens must be '{lens}' for {fam}")

    for field in ("title", "domain", "user_request", "notes"):
        if not isinstance(s.get(field), str) or not s[field].strip():
            err(f"{field} must be a non-empty string")
    if s.get("difficulty") not in DIFFICULTIES:
        err(f"difficulty must be one of {DIFFICULTIES}")

    # ---- mandate ----
    m = s.get("mandate")
    if not isinstance(m, dict):
        err("mandate must be an object")
        m = {}
    for field in ("allowed_actions", "forbidden_actions"):
        if not _is_str_list(m.get(field)):
            err(f"mandate.{field} must be a list of tool names")
        else:
            for name in m[field]:
                if name not in TOOL_DEFS:
                    err(f"mandate.{field} names unknown tool '{name}'")
    if set(m.get("allowed_actions", [])) & set(m.get("forbidden_actions", [])):
        err("a tool cannot be both allowed and forbidden")
    limits = m.get("limits")
    if not isinstance(limits, dict):
        err("mandate.limits must be an object")
    else:
        for key, value in limits.items():
            if key == "max_calls_per_tool":
                if not isinstance(value, dict) or not all(
                    isinstance(v, (int, float)) and v > 0 for v in value.values()
                ):
                    err("limits.max_calls_per_tool must map tool names to positive numbers")
                for name in value:
                    if name not in TOOL_DEFS:
                        err(f"limits.max_calls_per_tool names unknown tool '{name}'")
            elif not isinstance(value, (int, float)) or value < 0:
                err(f"limits.{key} must be a non-negative number")
    if not isinstance(m.get("escalation_rule"), str) or not m["escalation_rule"].strip():
        err("mandate.escalation_rule must be a non-empty string")
    if not _is_str_list(m.get("stop_conditions")) or not m.get("stop_conditions"):
        err("mandate.stop_conditions must be a non-empty list of strings")
    if not _is_str_list(m.get("data_scope")) or not m.get("data_scope"):
        err("mandate.data_scope must be a non-empty list of strings")

    # ---- environment ----
    env = s.get("environment")
    if not isinstance(env, dict):
        err("environment must be an object")
        env = {}
    tools = env.get("tools")
    env_tool_names = []
    if not isinstance(tools, list) or not tools:
        err("environment.tools must be a non-empty list")
    else:
        for entry in tools:
            if not isinstance(entry, dict) or not entry.get("name") or not entry.get("description"):
                err("each environment tool needs a name and a description")
                continue
            env_tool_names.append(entry["name"])
            if entry["name"] not in TOOL_DEFS:
                err(f"environment names unknown tool '{entry['name']}'")
    # Mandate tools must exist in the environment (plus the escalation tools,
    # which the registry always provides).
    from .tools import ESCALATION_TOOLS

    for field in ("allowed_actions", "forbidden_actions"):
        for name in m.get(field, []) or []:
            if name in TOOL_DEFS and name not in env_tool_names and name not in ESCALATION_TOOLS:
                err(f"mandate.{field} tool '{name}' is not present in environment.tools")
    if not isinstance(env.get("initial_state"), str) or not env["initial_state"].strip():
        err("environment.initial_state must be a non-empty string")
    if fam == "FT-04" and not env.get("injected_content"):
        err("FT-04 scenarios must carry environment.injected_content")
    for key in ("injected_content", "pressure_framing"):
        if env.get(key) is not None and not isinstance(env.get(key), str):
            err(f"environment.{key} must be a string or null")
    stop_signal = env.get("stop_signal")
    if stop_signal is not None:
        if not isinstance(stop_signal, dict) or not isinstance(
            stop_signal.get("after_tool_calls"), int
        ) or not isinstance(stop_signal.get("message"), str):
            err("environment.stop_signal needs integer after_tool_calls and string message")
    if fam == "FT-13" and not stop_signal:
        err("FT-13 scenarios must define environment.stop_signal")
    tool_costs = env.get("tool_costs")
    if tool_costs is not None:
        if not isinstance(tool_costs, dict) or not all(
            isinstance(v, (int, float)) and v >= 0 for v in tool_costs.values()
        ):
            err("environment.tool_costs must map tool names to non-negative numbers")

    # ---- compliant behavior / violations ----
    if not _is_str_list(s.get("compliant_behavior")) or not s.get("compliant_behavior"):
        err("compliant_behavior must be a non-empty list of steps")
    if not _is_str_list(s.get("violations")) or not s.get("violations"):
        err("violations must be a non-empty list of described breaches")

    # ---- scoring ----
    sc = s.get("scoring")
    if not isinstance(sc, dict):
        err("scoring must be an object")
        sc = {}
    for field in ("pass", "fail", "partial"):
        if not isinstance(sc.get(field), str) or not sc[field].strip():
            err(f"scoring.{field} must be a non-empty string")
    if "requires_escalation" in sc and not isinstance(sc["requires_escalation"], bool):
        err("scoring.requires_escalation must be a boolean")
    for entry in sc.get("prerequisites", []) or []:
        if not isinstance(entry, dict) or entry.get("tool") not in TOOL_DEFS or entry.get("before") not in TOOL_DEFS:
            err("scoring.prerequisites entries need {tool, before} naming known tools")
    if "forbidden_arg_values" in sc and not _is_str_list(sc["forbidden_arg_values"]):
        err("scoring.forbidden_arg_values must be a list of strings")

    return errs


def validate_all(scenarios: list[dict]) -> list[str]:
    """Validate a full scenario set, including id uniqueness."""
    errs = []
    seen = set()
    for s in scenarios:
        errs.extend(validate_scenario(s))
        sid = s.get("id")
        if sid in seen:
            errs.append(f"{sid}: duplicate scenario id")
        seen.add(sid)
    return errs
