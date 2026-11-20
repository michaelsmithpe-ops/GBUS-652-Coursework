"""Test the viewer's LIVE operator buttons against a real pipeline DRY RUN (no API calls, $0).

Run (from the repository folder, GBUS-652-Coursework):
    .venv\\Scripts\\python.exe capstone\\app\\test_viewer_live.py

Uses a temporary runs folder (FGB_RUNS_DIR), so the real runs/ and run-index.csv are untouched.
Script: event 07, steps 6 and 7, the dry-run reviewer REJECTs at step 7 (--dry-reject 7).
  step 6: page shows Approve / Reject, no override button -> click Approve (rung 2, no control room)
  step 7: page shows DO NOT ENGAGE + the override button -> submit it with NO reason (must refuse,
          nothing sent) -> submit with a reason -> request goes to the control room
          Operator view must not show the safety advice; the control room then STOPs (file answer)
  after:  page says the live run finished; a killed pipeline's stale request shows no buttons
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fgb-viewer-live-"))
os.environ["FGB_RUNS_DIR"] = str(TMP)          # must be set before the page is loaded

from streamlit.testing.v1 import AppTest      # noqa: E402

HERE = Path(__file__).resolve().parent
PAGE = str(HERE / "viewer.py")
OVERRIDE = "OVERRIDE REVIEWER REJECT — ENGAGE DRONE"
REASON = "Test: drone has circled for a minute; I want it down."
failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        failures.append(label)


def wait_for(pred, what: str, limit: float = 90):
    end = time.time() + limit
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {what}")


def pending(run_dir: Path, role: str, step: int) -> dict:
    def ok():
        try:
            d = json.loads((run_dir / "pending.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return d if d["role"] == role and d["step"] == step else None
    return wait_for(ok, f"step {step} {role} request")


def texts(at) -> str:
    parts = [m.value for m in at.markdown] + [m.value for m in at.caption]
    for kind in (at.info, at.warning, at.error, at.success):
        parts += [m.value for m in kind]
    return "\n".join(parts)


def labels(at) -> list[str]:
    return [b.label for b in at.button]


def page(view: str = "Operator") -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    if view != "Operator":
        at.radio[0].set_value(view).run()
    return at


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"Temp runs folder: {TMP}")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "pipeline.py"), "--event", "07", "--steps", "6,7", "--dry-run",
         "--web", "--dry-reject", "7"],
        cwd=str(HERE), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    try:
        run_dir = wait_for(lambda: next((d for d in TMP.iterdir() if d.is_dir()), None), "the run folder")

        # ---- step 6: normal recommendation ----
        req = pending(run_dir, "operator", 6)
        at = page()
        t, b = texts(at), labels(at)
        check(not at.exception, "page loads during a live run")
        check("LIVE" in t and run_dir.name in t, "sidebar follows the live run")
        check(at.toggle[0].value is True, "'Follow the live run' is on")
        check("Operator decision needed" in t, "operator panel shown")
        check("Approve: rung 2 as recommended" in b and any(l.startswith("Reject") for l in b),
              "Approve and Reject buttons shown")
        check(OVERRIDE not in b, "no override button when the reviewer approved")

        cr = page("Control room")
        check("Waiting for the operator" in texts(cr) and not any(l.startswith("Approve") for l in labels(cr)),
              "control-room view: waits for the operator, no operator buttons")

        at.button(key=f"accept-{req['id']}").click().run()
        t = texts(at)                          # the pipeline may already have moved on to step 7
        check("Decision sent" in t or "working" in t or "Operator decision needed" in t,
              "after Approve: sent (or pipeline already moved on); buttons for step 6 gone")
        check(f"accept-{req['id']}" not in [b.key for b in at.button], "step 6 Approve button gone")

        # ---- step 7: reviewer rejected -> DO NOT ENGAGE + override ----
        req = pending(run_dir, "operator", 7)
        at = page()
        t, b = texts(at), labels(at)
        check(not at.exception, "page loads at step 7")
        check("DO NOT ENGAGE" in t, "DO NOT ENGAGE banner shown")
        check("Analyst's original proposal" in t, "analyst's original proposal shown")
        check(OVERRIDE in b, "override button shown")
        check("Approve: DO NOT ENGAGE (keep tracking)" in b, "Approve is labeled DO NOT ENGAGE")

        ovr = next(x for x in at.button if x.label == OVERRIDE)
        ovr.click().run()
        time.sleep(1)
        check("A written reason is required" in texts(at), "override with no reason: refused on the page")
        check(not (run_dir / "answer.json").exists(), "override with no reason: nothing sent")
        check(json.loads((run_dir / "pending.json").read_text(encoding="utf-8"))["id"] == req["id"],
              "pipeline still waiting on the same request")

        at.text_area(key=f"override-reason-{req['id']}").input(REASON)
        next(x for x in at.button if x.label == OVERRIDE).click().run()
        t = texts(at)                          # the pipeline may already have posted the control-room request
        check("Decision sent" in t or "went to the control room" in t or "Agents working" in t,
              "override with a reason: sent (or the pipeline already moved on)")
        check(OVERRIDE not in labels(at), "override button gone after sending")

        # ---- step 7: control room request ----
        cr_req = pending(run_dir, "control_room", 7)
        cr = page("Control room")
        check("Control-room decision needed" in texts(cr), "control-room view: decision needed")
        op = page()
        t = texts(op)
        check("went to the control room" in t, "operator view: 'went to the control room'")
        check("Safety agent" not in t and "CONCUR" not in t, "operator view: NO safety advice shown")
        check("**Operator** (web): **OVERRIDE**" in t, "operator view shows its own override decision")

        answer = run_dir / "answer.json.tmp"     # the control room's buttons are tested elsewhere
        answer.write_text(json.dumps({"id": cr_req["id"], "decision": "stop", "reason": "Test stop."}), encoding="utf-8")
        os.replace(answer, run_dir / "answer.json")
        out, _ = proc.communicate(timeout=120)
        check(proc.returncode == 0, f"pipeline exited cleanly (code {proc.returncode})")

        rows = [json.loads(l) for l in (run_dir / "detail.jsonl").read_text(encoding="utf-8").splitlines()]
        ops = {r["step"]: r for r in rows if r["kind"] == "operator_decision"}
        crs = {r["step"]: r for r in rows if r["kind"] == "control_room_decision"}
        check(ops[6]["decision"]["decision"] == "accept" and ops[6]["decision"]["source"] == "web",
              "log: step 6 web accept")
        check(ops[7]["decision"]["decision"] == "override" and ops[7]["decision"]["reason"] == REASON,
              "log: step 7 web override with the typed reason")
        check(ops[7]["requested_rung"] == 3, "log: override requests the analyst's rung 3 proposal")
        check(crs[7]["decision"]["decision"] == "stop", "log: control-room stop")
        check(not [r for r in rows if r["kind"] == "web_answer_rejected"], "log: no answers rejected by the pipeline")

        op.run()
        check("finished" in texts(op), "page says the live run finished")

        # ---- a killed pipeline: stale request, no buttons ----
        fake = TMP / "99999999-999999-event-07-dryrun"
        fake.mkdir()
        (fake / "detail.jsonl").write_text(
            json.dumps({"kind": "run_start", "event": "07", "dry_run": True, "humans": "web"}) + "\n" +
            json.dumps({"kind": "step_start", "step": 3, "now": "2026-12-03 08:20:40"}) + "\n", encoding="utf-8")
        (fake / "pending.json").write_text(json.dumps(
            {"id": "x", "role": "operator", "step": 3, "choices": ["accept"], "do_not_engage": False,
             "shown": {"do_not_engage": False, "recommended_rung": 2}}), encoding="utf-8")
        old = time.time() - 60
        os.utime(fake / "pending.json", (old, old))
        at = page()
        check("stopped answering" in texts(at), "stale request: warning shown")
        check(not any(l.startswith("Approve") for l in labels(at)), "stale request: no buttons")
    finally:
        if proc.poll() is None:
            proc.kill()

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
