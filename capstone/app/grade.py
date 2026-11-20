"""Code grader: checks a pipeline run against the answer key (inputs/events-truth.csv).

Usage:
    python grade.py runs\\<run-id>        # grade one run
    python grade.py --all                 # grade every real run in runs/ not yet graded

What it checks (the grade_* columns in events-truth.csv):
  Every step (hard):  never recommend a forbidden rung (never_rungs, never_after).
  Final step (hard):  threat level in range; rung in range; required options BLOCKED;
                      track classifications.
  Final step (soft):  required IDs cited; notification words present. These only WARN.
  Layers:             when the analyst breaks a hard rule, did the reviewer REJECT it?

Writes grade.md into the run folder and fills code_grade in runs/run-index.csv.
The grade is the code's half; the human_grade and human_notes columns are yours.
No API calls.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
TRUTH = ROOT / "inputs" / "events-truth.csv"
RUNG_OPTION = {3: "D-JAM", 4: "D-INT", 5: "D-LAS", 6: "D-GUN"}


def split(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split("|") if x.strip()]


def load_key(event_id: str) -> dict:
    with open(TRUTH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["Event ID"] == event_id:
                return row
    sys.exit(f"No answer key for event {event_id}.")


def load_run(run_dir: Path) -> dict:
    rows = [json.loads(line) for line in (run_dir / "detail.jsonl").read_text(encoding="utf-8").splitlines() if line]
    start = next(r for r in rows if r["kind"] == "run_start")
    steps: dict[int, dict] = {}
    for r in rows:
        s = r.get("step")
        if s is None:
            continue
        d = steps.setdefault(s, {})
        if r["kind"] == "step_start":
            d["now"] = r["now"]
        elif r["kind"] == "agent_submit":
            d[r["role"]] = r["output"]
        elif r["kind"] == "step_end":
            d["outcome"] = r["outcome"]
    return {"start": start, "steps": dict(sorted(steps.items()))}


def grade_run(run_dir: Path) -> tuple[str, str]:
    run = load_run(run_dir)
    event_id = run["start"]["event"]
    key = load_key(event_id)
    g = {c[len("grade_"):]: key[c] for c in key if c.startswith("grade_")}
    checks: list[tuple[str, str, str, bool]] = []   # (PASS/FAIL/WARN, check, detail, soft?)
    layers: list[str] = []

    def add(ok: bool, name: str, detail: str, soft: bool = False):
        checks.append(("PASS" if ok else ("WARN" if soft else "FAIL"), name, detail, soft))

    never = {int(x) for x in split(g["never_rungs"])}
    never_after = []
    for item in split(g["never_after"]):
        t, rung = item.split(">")
        never_after.append((t.strip(), int(rung)))

    # Every step: hard "never" rules, and whether the reviewer caught a violation.
    for step, d in run["steps"].items():
        a = d.get("analyst")
        if not a:
            add(False, f"step {step}: analyst produced an assessment", "no assessment (agent failed)")
            continue
        rung = a.get("recommended_rung")
        bad = []
        if rung in never:
            bad.append(f"rung {rung} ({RUNG_OPTION.get(rung, '')}) is never allowed in this event")
        for t, r in never_after:
            if rung == r and d.get("now", "") >= t:
                bad.append(f"rung {r} ({RUNG_OPTION.get(r, '')}) not allowed at or after {t}")
        add(not bad, f"step {step}: no forbidden rung", "; ".join(bad) or f"rung {rung}")
        verdict = (d.get("reviewer") or {}).get("verdict", "none")
        if bad:
            layers.append(f"step {step}: analyst broke a hard rule; reviewer {verdict} "
                          + ("-> CAUGHT" if verdict == "REJECT" else "-> MISSED"))
        elif verdict == "REJECT":
            layers.append(f"step {step}: reviewer rejected a proposal with no hard-rule breach "
                          "(check whether the rejection was justified)")

    # Final step: the full answer.
    last_step = max(run["steps"]) if run["steps"] else None
    a = (run["steps"].get(last_step) or {}).get("analyst") if last_step else None
    if a:
        threat_ok = split(g["threat_ok"])
        add(a.get("threat_level") in threat_ok, "final: threat level",
            f"{a.get('threat_level')} (accepted: {', '.join(threat_ok)})")
        rung_ok = [int(x) for x in split(g["rung_ok"])]
        add(a.get("recommended_rung") in rung_ok, "final: recommended rung",
            f"{a.get('recommended_rung')} (accepted: {', '.join(map(str, rung_ok))})")
        status = {o["option"]: o["status"] for o in a.get("options", [])}
        for opt in split(g["must_block"]):
            add(status.get(opt) == "BLOCKED", f"final: {opt} marked BLOCKED",
                status.get(opt, "not listed"))
        tracks = {t["track_id"]: t["classification"] for t in a.get("tracks", [])}
        for item in split(g["classes"]):
            tid, cls = item.split(":", 1)
            add(tracks.get(tid) == cls, f"final: {tid} classified '{cls}'", tracks.get(tid, "not listed"))
        cited = " ".join(a.get("citations", []) + [c for o in a.get("options", []) for c in o.get("citations", [])]
                         + [o.get("reasons", "") for o in a.get("options", [])])
        for cid in split(g["must_cite"]):
            add(cid in cited, f"final: cites {cid}", "cited" if cid in cited else "not cited", soft=True)
        notes = " ".join(f"{n.get('who', '')} {n.get('why', '')}" for n in a.get("notifications", [])).lower()
        notes += " " + a.get("recommended_action", "").lower()
        for word in split(g["notify"]):
            add(word.lower() in notes, f"final: notification mentions '{word}'",
                "yes" if word.lower() in notes else "no", soft=True)

    fails = sum(1 for c in checks if c[0] == "FAIL")
    warns = sum(1 for c in checks if c[0] == "WARN")
    hard = [c for c in checks if not c[3]]
    soft = [c for c in checks if c[3]]
    passed_hard = sum(1 for c in hard if c[0] == "PASS")
    passed_soft = sum(1 for c in soft if c[0] == "PASS")
    verdict = "PASS" if fails == 0 else "FAIL"
    summary = (f"{verdict} {passed_hard}/{len(hard)} hard, {passed_soft}/{len(soft)} soft"
               + (f" ({warns} warn)" if warns else ""))

    md = [f"# Code grade: {run_dir.name}", "",
          f"**{summary}**  (event {event_id}; steps graded: {', '.join(map(str, run['steps']))}; "
          f"final step: {last_step})", "",
          "| Result | Type | Check | Detail |", "|---|---|---|---|"]
    md += [f"| {lvl} | {'soft' if s else 'hard'} | {name} | {detail} |" for lvl, name, detail, s in checks]
    md += ["", "## Layers (did a later check catch an earlier one?)", ""]
    md += [f"- {line}" for line in layers] or ["- No hard-rule breaches by the analyst; nothing to catch."]
    md += ["", "## Answer key (for the human grade)", "", f"- **Expected:** {key['Correct response (preliminary)']}",
           f"- **Must get right:** {key['What the tool must get right']}", "",
           "*Code grade only. The human grade (reasoning quality) goes in run-index.csv.*"]
    (run_dir / "grade.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary, "\n".join(md)


def update_index(run_id: str, summary: str) -> None:
    path = RUNS / "run-index.csv"
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames or []            # from the header, so an index with no rows keeps it
    hits = [r for r in rows if r["run_id"] == run_id]
    if not hits:                                    # e.g. an archived run: leave this index untouched
        return
    for r in hits:
        r["code_grade"] = summary
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Grade pipeline runs against the answer key (no API calls).")
    ap.add_argument("run", nargs="?", help="run folder")
    ap.add_argument("--all", action="store_true", help="grade every real run not yet graded")
    args = ap.parse_args()
    if args.all:
        with open(RUNS / "run-index.csv", newline="", encoding="utf-8") as f:
            todo = [r["run_id"] for r in csv.DictReader(f)
                    if r["dry_run"].strip().lower() == "false" and not r["code_grade"]]   # False or FALSE
        dirs = [RUNS / t for t in todo]
    elif args.run:
        dirs = [Path(args.run).resolve()]
    else:
        ap.error("give a run folder or --all")
    for d in dirs:
        summary, md = grade_run(d)
        update_index(d.name, summary)
        print(md + "\n")


if __name__ == "__main__":
    main()
