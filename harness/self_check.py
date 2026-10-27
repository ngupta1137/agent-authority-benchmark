"""Self-check for the Agent Authority Benchmark.

Run from the repository root:

    python -m harness.self_check

It proves the benchmark is internally consistent before any model is run:

1. All 50 scenarios load and validate against the field spec.
2. The per-family distribution matches the locked spec exactly.
3. The scripted compliant agent passes all 50 scenarios (ACS 100).
4. The scripted violating agent fails all 50 scenarios — every scenario
   is capable of being failed by its signature breach.

Exits non-zero if any assertion fails.
"""

from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.adapters import ScriptedCompliantAgent, ScriptedViolatingAgent
from harness.loader import load_scenarios, validate_all
from harness.runner import run_scenario
from harness.scorer import compute_acs, score_run

EXPECTED_DISTRIBUTION = {
    "FT-01": 5, "FT-02": 5, "FT-03": 4, "FT-04": 6, "FT-05": 4,
    "FT-06": 3, "FT-07": 2, "FT-08": 4, "FT-09": 3, "FT-10": 4,
    "FT-11": 2, "FT-12": 3, "FT-13": 2, "FT-14": 3,
}
EXPECTED_TOTAL = 50

SCENARIOS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "scenarios", "scenarios.jsonl"
)


def main() -> int:
    scenarios = load_scenarios(SCENARIOS_PATH)
    print(f"Loaded {len(scenarios)} scenarios from scenarios.jsonl")

    errors = validate_all(scenarios)
    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print("  -", e)
        return 1
    print("Validation: all scenarios valid against the field spec")

    counts = Counter(s["family"] for s in scenarios)
    assert len(scenarios) == EXPECTED_TOTAL, (
        f"expected {EXPECTED_TOTAL} scenarios, got {len(scenarios)}"
    )
    assert dict(counts) == EXPECTED_DISTRIBUTION, (
        f"distribution mismatch: {dict(counts)} != {EXPECTED_DISTRIBUTION}"
    )
    print("Distribution: matches spec " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    for agent_cls, expect in (
        (ScriptedCompliantAgent, "pass"),
        (ScriptedViolatingAgent, "fail"),
    ):
        agent = agent_cls()
        verdicts = []
        problems = []
        for scenario in scenarios:
            result = run_scenario(agent, scenario)
            verdict = score_run(scenario, result)
            verdicts.append(verdict)
            if verdict["verdict"] != expect:
                problems.append(
                    f"{scenario['id']}: expected {expect}, got "
                    f"{verdict['verdict']} {verdict['hard_violations']} {verdict['notes']}"
                )
        summary = compute_acs(verdicts)
        print(
            f"{agent.name}: ACS {summary['acs']} | "
            f"pass {summary['passed']} / partial {summary['partial']} / "
            f"fail {summary['failed']} | "
            f"hard-violation rate {summary['hard_violation_rate']}"
        )
        if problems:
            print(f"SELF-CHECK FAILURES for {agent.name}:")
            for p in problems:
                print("  -", p)
            return 1

    print("SELF-CHECK PASSED: compliant agent passes all 50; "
          "violating agent fails all 50.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
