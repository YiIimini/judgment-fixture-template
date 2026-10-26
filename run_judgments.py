#!/usr/bin/env python3
"""Minimal judgment-fixture runner (v2).

Exit codes
  0  all positive rules passed; every negative control went red for the RIGHT reason
  2  a positive rule failed
  3  NO_NEGATIVE_CONTROL: no negative control in the suite (or a negative control did not go red)
  4  fixture-bad: malformed row, unknown expect key, missing/mixed criterion_version
  5  SELFTEST_FAILED: the checker cannot produce both red and green through check()
  6  UNKNOWN_MISSING_FIELD: observation lacks a required field and the rule did not declare it
  7  NEGATIVE_RED_WRONG_REASON: a negative control went "red" via UNKNOWN instead of FAIL

Design notes (each one is a bug we hit and then fixed):
  * expected values come only from this file, never from the code under test;
  * unknown must never be silently treated as pass (positive rule) **or as red** (negative control);
  * a suite without a negative control is not green, it is unverified;
  * selftest needs a must-red twin AND a must-green twin, otherwise a constant-FAIL
    checker passes selftest and turns every negative control "red";
  * criterion_version must be an int; null/missing/mixed -> fixture-bad.
"""
import argparse, json, sys

REQUIRED = ("rule_no", "id", "kind", "criterion_version", "given", "expect")
KNOWN_EXPECT_KEYS = {"total"}


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
                bad.append((lineno, f"not json: {exc}")); continue
            missing = [k for k in REQUIRED if k not in rule]
            if missing:
                bad.append((lineno, f"missing keys: {missing}")); continue
            if not isinstance(rule["criterion_version"], int) or isinstance(rule["criterion_version"], bool):
                bad.append((lineno, f"criterion_version must be int, got {rule['criterion_version']!r}"))
                continue
            exp = rule.get("expect")
            if not isinstance(exp, dict) or len(exp) != 1:
                bad.append((lineno, "expect must be an object with exactly one key")); continue
            key = next(iter(exp))
            if key not in KNOWN_EXPECT_KEYS:
                bad.append((lineno, f"unknown expect key {key!r} (known: {sorted(KNOWN_EXPECT_KEYS)})"))
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


def observe(given):
    """Observation: sum of item values, but ONLY over fields that exist.

    Returns None when anything required is absent. It never invents 0.
    """
    items = given.get("items")
    if items is None:
        return None
    total = 0
    for item in items:
        if not isinstance(item, dict) or "value" not in item:
            return None
        total += item["value"]
    return total


def check(rule):
    """Return (verdict, detail); verdict in PASS / FAIL / UNKNOWN_MISSING_FIELD."""
    observed = observe(rule["given"])
    key = next(iter(rule["expect"]))
    expected = rule["expect"][key]
    if observed is None:
        return "UNKNOWN_MISSING_FIELD", "observation has no complete items/values"
    if observed == expected:
        return "PASS", f"{key}={observed}"
    return "FAIL", f"{key}: expected {expected}, got {observed}"


def run(path, allow_no_negative=False):
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

    negatives = [r for r in rules if r.get("control") == "negative"]
    if not negatives and not allow_no_negative:
        print("[no-negative-control] suite has no negative control: unverified, not green")
        return 3

    failed_positive, red_right, red_wrong, unknown, declared_unknown_miss = [], 0, [], 0, []
    for rule in rules:
        verdict, detail = check(rule)
        shown = f"{rule['rule_no']} {rule['id']}"
        is_negative = rule.get("control") == "negative"
        declares_unknown = rule.get("on_violation") == "UNKNOWN_MISSING_FIELD"

        if verdict == "UNKNOWN_MISSING_FIELD":
            unknown += 1
            if is_negative:
                red_wrong.append((shown, "UNKNOWN", detail))
                print(f"  NEGATIVE-CONTROL UNKNOWN <-- red for the wrong reason {shown}: {detail}")
            elif declares_unknown:
                declared_unknown_miss.append((shown, detail))
                print(f"  UNKNOWN (declared) {shown}: {detail}")
            else:
                failed_positive.append((shown, verdict, detail))
                print(f"  UNKNOWN {shown}: {detail}")
            continue

        if is_negative:
            if verdict == "FAIL":
                red_right += 1
                print(f"  NEGATIVE-CONTROL RED (as expected) {shown}: {detail}")
            else:
                red_wrong.append((shown, verdict, detail))
                print(f"  NEGATIVE-CONTROL PASSED <-- suite untrustworthy {shown}: {detail}")
            continue

        if declares_unknown:
            # Declared outcome was UNKNOWN, but the rule actually computed a real verdict.
            failed_positive.append((shown, f"DECLARED_UNKNOWN_GOT_{verdict}", detail))
            print(f"  FAIL (declared unknown, got {verdict}) {shown}: {detail}")
            continue

        if verdict == "PASS":
            print(f"  PASS {shown}: {detail}")
        else:
            failed_positive.append((shown, verdict, detail))
            print(f"  FAIL {shown}: {detail}")

    print()
    if red_wrong:
        print(f"[negative-wrong-reason] {len(red_wrong)} negative control(s) not red for the right reason.")
        return 7
    if failed_positive:
        print(f"[failed] {len(failed_positive)} rule(s) failed.")
        return 2
    print(f"[green] {red_right} negative control(s) red as expected; "
          f"{len(declared_unknown_miss)} declared-unknown; {unknown} unknown.")
    return 0


def selftest():
    """Prove the checker can produce BOTH red and green through check().

    A constant-FAIL checker passes a must-red-only selftest; the must-green twin
    is what catches it.
    """
    must_red = {"rule_no": "S-1", "id": "selftest-must-red", "kind": "positive", "control": "none",
                "criterion_version": 1, "given": {"items": [{"id": "a", "value": 1}]},
                "expect": {"total": 999}}
    must_green = {"rule_no": "S-2", "id": "selftest-must-green", "kind": "positive", "control": "none",
                  "criterion_version": 1, "given": {"items": [{"id": "a", "value": 1}]},
                  "expect": {"total": 1}}
    v_red, d_red = check(must_red)
    v_green, d_green = check(must_green)
    if v_red == "PASS":
        print(f"[selftest] FAILED: must-red rule judged {v_red}"); return 5
    if v_green != "PASS":
        print(f"[selftest] FAILED: must-green rule judged {v_green} ({d_green}) -- checker cannot pass anything"); return 5
    print(f"[selftest] OK: must-red judged {v_red}; must-green judged PASS")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", nargs="?", default="judgments.example.jsonl")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--allow-no-negative", action="store_true",
                    help="explicitly accept a suite without negative controls (not recommended)")
    args = ap.parse_args()
    code = selftest()
    if code:
        return code
    return run(args.fixture, args.allow_no_negative)


if __name__ == "__main__":
    sys.exit(main())
