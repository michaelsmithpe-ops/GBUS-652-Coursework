"""Test the escalation guardrail (guardrail.py + its use in pipeline.py). No API calls.

Unit checks on the rules, then three free end-to-end dry runs in a temp runs folder:
  1. event 11 --dry-overrung 3   : LOW + rung 6 -> DO NOT ENGAGE (ROE-4.1), nothing to the control room
  2. event 07 (decisions.json)   : step 6 override to rung 3 is STOPPED; step 7's rung 3 -> blocked (ROE-4.4)
     + event 03 (test decisions)  : a STOP of rung 2 blocks rung 3 later
  3. event 07 --dry-overrung 6   : blocked step 6 + scripted operator override -> override refused
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guardrail as G  # noqa: E402

failures = 0


def check(ok: bool, what: str) -> None:
    global failures
    print(("  PASS  " if ok else "  FAIL  ") + what)
    failures += not ok


print("Unit checks")
check(G.ladder() == {0: "NONE", 1: "NONE", 2: "LOW", 3: "MEDIUM", 4: "HIGH", 5: "HIGH", 6: "CRITICAL"},
      f"ladder read from ROE-4.1: {G.ladder()}")
check([G.max_rung(t) for t in G.THREATS] == [1, 2, 3, 5, 6], "max rung per threat: NONE 1, LOW 2, MEDIUM 3, HIGH 5, CRITICAL 6")
g = G.check({"threat_level": "LOW", "recommended_rung": 6}, "2026-12-05 09:40:00")
check(g["blocked"] and "ROE-4.1" in g["reasons"][0], "LOW + rung 6 is blocked (ROE-4.1)")
check(g["max_allowed"] == 2, "LOW: highest allowed rung is 2")
check(not G.check({"threat_level": "MEDIUM", "recommended_rung": 3}, "2026-12-05 09:40:00")["blocked"],
      "MEDIUM + rung 3 (jammer) passes")
check(not G.check({"threat_level": "CRITICAL", "recommended_rung": 6, "tracks": [{"pvid": True}]},
                  "2026-12-05 09:40:00")["blocked"], "CRITICAL + rung 6 passes the ladder")
g = G.check({"threat_level": "CRITICAL", "recommended_rung": 5}, "2026-12-05 15:32:00", stopped_rung=4, stopped_step=6)
check(g["blocked"] and "ROE-4.4" in " ".join(g["reasons"]) and g["max_allowed"] == 3,
      "after a STOP of rung 4: rung 5 is blocked (ROE-4.4), highest allowed 3 (the T10 step 7 case)")
check(not G.check({"threat_level": "HIGH", "recommended_rung": 3}, "2026-12-05 15:32:00", 4, 6)["blocked"],
      "after a STOP of rung 4: rung 3 still passes")
w = G.check({"threat_level": "HIGH", "recommended_rung": 5}, "2026-12-01 10:00:00")["warnings"]
check(any("equipment" in x and "D-LAS" in x and "H-02" in x for x in w), "WARN: laser DOWN at 2026-12-01 10:00 (H-02)")
check(any("PVID" in x for x in w), "WARN: laser with no PVID")
check(not G.check({"threat_level": "HIGH", "recommended_rung": 5}, "2026-12-01 10:00:00")["blocked"],
      "warnings never block")
w = G.check({"threat_level": "LOW", "recommended_rung": 2, "citations": ["ROE-4.1", "N-17", "H-03", "ROE-9.9"],
             "options": [{"citations": ["N-99"]}]}, "2026-12-05 09:40:00")["warnings"]
check(len(w) == 1 and "ROE-9.9" in w[0] and "N-99" in w[0] and "ROE-4.1" not in w[0],
      f"WARN: unknown citations only ({w})")


print("\nUnit checks: Section 5 number rules (c), on real event data")


def s5(event: str, rung: int, now: str, threat: str = "CRITICAL", tid: str = "T-1",
       cls: str = "unknown drone") -> str:
    a = {"threat_level": threat, "recommended_rung": rung,
         "tracks": [{"track_id": tid, "classification": cls}]}
    return " ".join(G.section5_reasons(rung, a, event, now))


r = s5("05", 3, "2026-12-02 11:32:00")
check("ROE-5.1" in r, "event 05: jammer blocked, RF-silent drone (ROE-5.1)")
check(s5("05", 4, "2026-12-02 11:32:00") == "", "event 05: interceptor passes")
check(s5("05", 5, "2026-12-02 11:30:40") == "", "event 05 step 3: laser passes (over open water)")
check("ROE-5.7" in s5("05", 5, "2026-12-02 11:32:00"), "event 05 step 7: laser blocked, elevation 71 deg (ROE-5.7)")
r = s5("05", 6, "2026-12-02 11:32:00")
check("ROE-5.12" in r and "ROE-5.14" in r and "D-INT" in r, "event 05: gun blocked: sector, and not the last resort")
check(s5("03", 3, "2026-12-01 06:44:00") == "", "event 03: jammer passes (live link)")
r = s5("03", 5, "2026-12-01 06:44:00")
check("visibility 0.8 km" in r and "no current view" in r, "event 03: laser blocked by fog and no camera view (ROE-5.10)")
r = s5("08", 5, "2026-12-03 16:52:00")
check("ROE-5.7" in r and "ROE-5.8" in r and "N-09" in r, "event 08: laser blocked: elevation and satellite window N-09")
check("Z-HOUSE" in s5("06", 6, "2026-12-02 21:12:00"), "event 06: gun blocked, housing behind the target (ROE-5.13)")
check("Z-HOUSE" in s5("06", 5, "2026-12-02 21:12:00"), "event 06: laser blocked, housing in the beam path (ROE-5.11)")
check(s5("06", 4, "2026-12-02 21:12:00") == "", "event 06: interceptor passes")
check(s5("10", 4, "2026-12-05 15:32:00", tid="T-2") == "", "event 10: interceptor against T-2 passes")
check("N-16" in s5("10", 5, "2026-12-05 15:32:00"), "event 10: laser at T-1 crosses the regatta area N-16 (ROE-5.11)")
check(s5("05", 3, "2026-12-02 11:32:00", cls="not a drone") == "", "tracks that are not unknown drones are not checked")
check(s5("05", 2, "2026-12-02 11:32:00") == "", "rungs 0-2 have no Section 5 rules")
g = G.check({"threat_level": "HIGH", "recommended_rung": 3,
             "tracks": [{"track_id": "T-1", "classification": "unknown drone"}]}, "2026-12-02 11:32:00", event_id="05")
check(g["blocked"] and any("ROE-5.1" in x for x in g["reasons"]), "check(..., event_id) blocks with Section 5 reasons")
check(not G.check({"threat_level": "HIGH", "recommended_rung": 3,
                   "tracks": [{"track_id": "T-1", "classification": "unknown drone"}]},
                  "2026-12-02 11:32:00")["blocked"], "without event_id only rules (a) and (b) run")
g = G.check({"threat_level": "HIGH", "recommended_rung": 3, "tracks": [{"track_id": "T-1",
             "classification": "unknown drone"}]}, "2026-12-02 11:32:00", event_id="99")
check(not g["blocked"] and any("could not run" in w for w in g["warnings"]),
      "if the Section 5 checks fail, the people are warned (no crash, no silent pass)")


def dry_run(event: str, *extra: str) -> list[dict]:
    env = {**os.environ, "FGB_RUNS_DIR": RUNS, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, str(HERE / "pipeline.py"), "--event", event, "--dry-run", *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if p.returncode != 0:
        print(p.stdout[-2000:], p.stderr[-2000:])
    run_dir = sorted(Path(RUNS).glob(f"*-event-{event}-dryrun"))[-1]
    return [json.loads(x) for x in (run_dir / "detail.jsonl").read_text(encoding="utf-8").splitlines() if x]


def at(rows, step, kind):
    return [r for r in rows if r.get("step") == step and r["kind"] == kind]


with tempfile.TemporaryDirectory(prefix="fgb-guardrail-") as RUNS:
    print("\nEnd to end 1: event 11 --dry-overrung 3 (LOW + gun)")
    rows = dry_run("11", "--dry-overrung", "3")
    g3 = at(rows, 3, "guardrail")[0]
    s3 = at(rows, 3, "shown_to_operator")[0]["shown"]
    check(g3["blocked"] and g3["analyst_rung"] == 6, "step 3: guardrail blocked rung 6")
    check(s3["do_not_engage"] and s3["blocked_by"] == "guardrail" and s3["recommended_rung"] <= 2,
          f"step 3: operator sees DO NOT ENGAGE (guardrail), rung {s3['recommended_rung']}")
    check(not at(rows, 3, "control_room_decision"), "step 3: nothing sent to the control room")
    check(all(r["shown"]["recommended_rung"] <= 2 for r in rows if r["kind"] == "shown_to_operator"
              if r["step"] != 7), "steps 1-6: nothing above rung 2 shown")
    check(not any(r["blocked"] for r in rows if r["kind"] == "guardrail" and r["step"] != 3),
          "other steps: guardrail did not block")

    print("\nEnd to end 2a: event 07 with decisions.json (step 6 override to rung 3 STOPPED, then step 7 rung 3)")
    rows = dry_run("07")
    cr6 = at(rows, 6, "control_room_decision")
    check(bool(cr6) and cr6[0]["decision"]["decision"] == "stop", "step 6: control room stopped the rung 3 override")
    g7 = at(rows, 7, "guardrail")[0]
    check(g7["blocked"] and "ROE-4.4" in " ".join(g7["reasons"]), "step 7: rung 3 blocked (control room stopped rung 3)")
    check(at(rows, 7, "shown_to_operator")[0]["shown"]["do_not_engage"], "step 7: operator sees DO NOT ENGAGE")
    check(not at(rows, 7, "control_room_decision"), "step 7: nothing sent to the control room")

    print("\nEnd to end 2b: STOP means stop (test decisions: step 6 override to rung 2, control room STOPS)")
    test_decisions = Path(RUNS) / "decisions-test.json"
    test_decisions.write_text(json.dumps({"defaults": {"operator": "accept", "control_room": "follow_safety_advice"},
        "events": {"03": {"6": {"operator": "override", "operator_reason": "test",
                                "override_action": {"rung": 2, "action": "TEST: security"},
                                "control_room": "stop", "control_room_reason": "TEST stop"}}}}), encoding="utf-8")
    os.environ["FGB_DECISIONS_FILE"] = str(test_decisions)
    rows = dry_run("03")
    del os.environ["FGB_DECISIONS_FILE"]
    cr6 = at(rows, 6, "control_room_decision")
    check(bool(cr6) and cr6[0]["decision"]["decision"] == "stop", "step 6: control room stopped the rung 2 request")
    g7 = at(rows, 7, "guardrail")[0]
    check(g7["blocked"] and "ROE-4.4" in " ".join(g7["reasons"]) and g7["analyst_rung"] == 3,
          "step 7: analyst's rung 3 blocked (control room stopped rung 2 at step 6)")
    s7 = at(rows, 7, "shown_to_operator")[0]["shown"]
    check(s7["do_not_engage"] and s7["recommended_rung"] <= 1, f"step 7: DO NOT ENGAGE, rung {s7['recommended_rung']}")
    check(not at(rows, 7, "control_room_decision"), "step 7: nothing sent to the control room")

    print("\nEnd to end 3: event 07 --dry-overrung 6 (blocked, then the scripted operator override)")
    rows = dry_run("07", "--dry-overrung", "6")
    check(at(rows, 6, "guardrail")[0]["blocked"], "step 6: guardrail blocked rung 6")
    ref = at(rows, 6, "guardrail_override_refused")
    check(bool(ref) and ref[0]["requested_rung"] == 6, "step 6: operator override to rung 6 refused")
    check(not at(rows, 6, "control_room_decision"), "step 6: nothing sent to the control room")
    check(at(rows, 6, "operator_decision")[0]["requested_rung"] == 1, "step 6: request falls back to rung 1 (tracking)")
    check(not at(rows, 7, "guardrail")[0]["blocked"], "step 7: no STOP happened, so rung 3 passes")

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURE(S)")
sys.exit(1 if failures else 0)
