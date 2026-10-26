#!/usr/bin/env python3
"""Minimal judgment-fixture runner.

Exit codes:
  0  all positive rules pass, all negative controls red (or no negative control declared)
  2  a positive rule failed
  3  a negative control did NOT go red -> the whole suite is untrustworthy
  4  criterion_version missing or mixed within one batch
  5  selftest failed: the checker itself cannot go red
  6  UNKNOWN_MISSING_FIELD: observation lacks a required field

Design notes (why it looks like this):
  * expected values come only from this file, never from the code under test;
  * every positive rule SHOULD have a paired negative control ("negative" control);
  * a negative control is expected to FAIL. If it passes, the suite is lying.
  * --selftest builds a deliberately wrong rule in memory and runs it through the
    same check(): if it cannot go red, the checker is broken.
"""
import argparse, json, sys

REQUIRED = ("rule_no", "id", "kind", "criterion_version", "given", "expect")


def load_rules(path):
    rules, bad = [], []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rule = json.loads(line)
            except json.JSONDecodeError as exc:
                bad.append((lineno, f"not json: {exc}"))
                continue
            missing = [k for k in REQUIRED if k not in rule]
            if missing:
                bad.append((lineno, f"missing keys: {missing}"))
                continue
            rules.append(rule)
    return rules, bad


def version_guard(rules):
    versions = {r["criterion_version"] for r in rules}
    if not versions:
        return "empty", versions
    if len(versions) > 1:
        return "mixed", versions
    return "ok", versions


def total_of(given):
    """Observation: sum of item values, but ONLY over fields that exist.

    Note: this returns None when the items list is absent. It never invents 0.
    """
    items = given.get("items")
    if items is None:
        return None
    total = 0
    for item in items:
        if "value" not in item:
            return None
        total += item["value"]
    return total


def check(rule):
    """Return (verdict, detail). verdict in PASS / FAIL / UNKNOWN_MISSING_FIELD."""
    observed = total_of(rule["given"])
    expected = rule["expect"].get("total")
    if observed is None:
        return "UNKNOWN_MISSING_FIELD", "observation has no complete items/values"
    expected_key = next(iter(rule["expect"]))
    obs = rule["given"] and {expected_key: observed}
    if obs[expected_key] == expected:
        return "PASS", f"{expected_key}={observed}"
    return "FAIL", f"{expected_key}: expected {expected}, got {observed}"


def run(path):
    rules, bad = load_rules(path)
    if bad:
        for lineno, why in bad:
            print(f"[fixture-bad] line {lineno}: {why}")
        return 4
    state, versions = version_guard(rules)
    if state == "mixed":
        print(f"[fixture-bad] mixed criterion_version in one batch: {sorted(versions)}")
        return 4
    print(f"[version] criterion_version={sorted(versions)}")

    failed_positive, negative_ok, negative_bad, unknown = [], 0, [], 0
    for rule in rules:
        verdict, detail = check(rule)
        is_negative = rule.get("control") == "negative"
        shown = f"{rule['rule_no']} {rule['id']}"
        if verdict == "UNKNOWN_MISSING_FIELD":
            unknown += 1
            print(f"  UNKNOWN {shown}: {detail}")
            # A rule may DECLARE that unknown is the expected outcome (on_violation).
            # Declaring it is different from silently treating unknown as pass.
            if is_negative or rule.get("on_violation") == "UNKNOWN_MISSING_FIELD":
                negative_ok += 1
            else:
                failed_positive.append((shown, verdict, detail))
            continue
        if is_negative:
            if verdict == "FAIL":
                negative_ok += 1
                print(f"  NEGATIVE-CONTROL RED (as expected) {shown}: {detail}")
            else:
                negative_bad.append((shown, verdict, detail))
                print(f"  NEGATIVE-CONTROL PASSED <-- suite untrustworthy {shown}: {detail}")
            continue
        if verdict == "PASS":
            print(f"  PASS {shown}: {detail}")
        else:
            failed_positive.append((shown, verdict, detail))
            print(f"  FAIL {shown}: {detail}")

    print()
    if negative_bad:
        print(f"[suite-untrustworthy] {len(negative_bad)} negative control(s) did not go red.")
        return 3
    if failed_positive:
        print(f"[failed] {len(failed_positive)} positive rule(s) failed.")
        return 2
    print(f"[green] {negative_ok} negative control(s) red as expected; {unknown} unknown.")
    return 0


def selftest():
    """Prove the checker itself can go red, independently of the fixture file."""
    broken = {
        "rule_no": "S-01",
        "id": "selftest-deliberately-wrong",
        "kind": "positive",
        "control": "none",
        "criterion_version": 1,
        "given": {"items": [{"id": "a", "value": 1}]},
        "expect": {"total": 999},
    }
    verdict, detail = check(broken)
    if verdict == "PASS":
        print("[selftest] FAILED: checker returned PASS for a deliberately wrong rule")
        return 5
    print(f"[selftest] OK: wrong rule judged {verdict} ({detail})")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", nargs="?", default="judgments.example.jsonl")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    code = selftest()
    if code:
        return code
    return run(args.fixture)


if __name__ == "__main__":
    sys.exit(main())
