"""Alder Creek evaluation (week 6 lecture example).

Runs every row of test-cases.csv (in this folder) through the assistant and
checks each reply in code:
  - the priority matches expected_priority;
  - the reply contains at least one must_say phrase (separated by |) and no
    must_not_say phrase, ignoring capital letters;
  - needs_person is true where the needs_person column says yes;
  - every dollar amount in the reply is $0, $89, $149, or $129.

Prints one line per case (PASS, or FAIL with every reason) and ends with the
number passed. A case whose reply the output guardrail held for a person ends
with "(held: <held_because>)". --save NAME writes the same output to a file,
and every case's full reply to NAME-replies (e.g. eval-3-replies.txt). A relative NAME
is saved in this folder (week-06/alder-creek), so Alder Creek output never
lands anywhere else.

Usage (from the repository folder):
    .venv\\Scripts\\python.exe week-06\\alder-creek\\evaluate.py
    .venv\\Scripts\\python.exe week-06\\alder-creek\\evaluate.py --save runs\\eval-1.txt

Each case is one API call (eight cases in all).
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import anthropic

import assistant  # assistant.py in this same folder

HERE = Path(__file__).resolve().parent
CASES_FILE = HERE / "test-cases.csv"

ALLOWED_DOLLARS = {0, 89, 149, 129}
DOLLAR_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")


def phrases(cell: str) -> list[str]:
    """Split a must_say / must_not_say cell on | into lower-case phrases."""
    return [p.strip().lower() for p in (cell or "").split("|") if p.strip()]


def check(row: dict, reply: dict) -> list[str]:
    """Return the reasons this reply fails its test case (empty list = PASS)."""
    reasons = []
    text = str(reply.get("reply", ""))
    low = text.lower()

    priority = reply.get("priority")
    if priority != row["expected_priority"]:
        reasons.append(f"priority {priority!r}, expected {row['expected_priority']!r}")

    must_say = phrases(row.get("must_say", ""))
    if must_say and not any(p in low for p in must_say):
        reasons.append("reply has none of the must_say phrases: " + " | ".join(must_say))

    said = [p for p in phrases(row.get("must_not_say", "")) if p in low]
    if said:
        reasons.append("reply has must_not_say phrase(s): " + " | ".join(said))

    if (row.get("needs_person") or "").strip().lower() == "yes" and reply.get("needs_person") is not True:
        reasons.append(f"needs_person is {reply.get('needs_person')!r}, expected true")

    for amount in DOLLAR_RE.findall(text):
        value = float(amount.replace(",", ""))
        if value not in ALLOWED_DOLLARS:
            reasons.append(f"dollar amount ${amount} is not on the fee list ($0, $89, $149, $129)")

    return reasons


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the Alder Creek assistant on test-cases.csv")
    parser.add_argument("--save", metavar="NAME",
                        help="also write the output to this file (relative names go in week-06/alder-creek)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with open(CASES_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    client = anthropic.Anthropic(api_key=assistant.load_api_key())
    lines, passed, replies = [], 0, []
    for row in rows:
        reply = {}
        try:
            reply = assistant.ask(row["request"], client)
            reasons = check(row, reply)
        except SystemExit as e:          # assistant.ask exits when the reply is not valid JSON
            reasons = [str(e).splitlines()[0]]
        except anthropic.APIError as e:
            reasons = [f"API error: {e.__class__.__name__}"]
        if reasons:
            line = f"{row['id']} FAIL: " + "; ".join(reasons)
        else:
            line = f"{row['id']} PASS"
            passed += 1
        if reply.get("held_because"):    # the output guardrail held this reply for a person
            line += f" (held: {reply['held_because']})"
        print(line, flush=True)
        lines.append(line)
        replies.append(f"=== {row['id']} ({row['type']}): {row['request']}\n"
                       + json.dumps(reply, indent=2, ensure_ascii=False))

    total = f"Passed: {passed} of {len(rows)}"
    print(total)
    lines.append(total)

    if args.save:
        out = Path(args.save)
        if not out.is_absolute():
            out = HERE / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Saved {out}")
        rep = out.with_name(out.stem + "-replies" + out.suffix)
        rep.write_text("\n\n".join(replies) + "\n", encoding="utf-8")
        print(f"Saved {rep}")


if __name__ == "__main__":
    main()
