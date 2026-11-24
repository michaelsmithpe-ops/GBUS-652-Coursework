"""Test the viewer's LIVE control-room buttons against a real pipeline DRY RUN (no API calls, $0).

Run (from the repository folder, GBUS-652-Coursework):
    .venv\\Scripts\\python.exe capstone\\app\\test_viewer_control_room.py

Uses a temporary runs folder (FGB_RUNS_DIR); the real runs/ and run-index.csv are untouched.
The operator's answers are written straight to answer.json (the operator page was tested in
test_viewer_live.py); the CONTROL ROOM decisions are made with the page's buttons.
  step 6: operator asks for a stronger action (rung 3 jammer)  -> control room: STOP with no
          reason (must refuse, nothing sent), then STOP with a reason
  step 7: the guardrail blocks rung 3 (stopped at step 6) and refuses the operator's override
  then a second dry run, step 7 only: reviewer REJECTs (--dry-reject 7), operator OVERRIDES ->
          page shows OPERATOR OVERRODE REVIEWER with both reasons side by side -> control room: APPROVE
  also:   NO countdown (no time limit); the safety agent's call in bold next to the buttons;
          Operator view never shows the control-room buttons or safety advice;
          a request with no safety advice is flagged NO SAFETY ADVICE AVAILABLE
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fgb-viewer-cr-"))
os.environ["FGB_RUNS_DIR"] = str(TMP)          # must be set before the page is loaded

from streamlit.testing.v1 import AppTest      # noqa: E402

HERE = Path(__file__).resolve().parent
PAGE = str(HERE / "viewer.py")
STOP = "Reject / STOP — do not carry out this request"
STOP_WHY = "Test: Patrol 2 has eyes on walkers on the beach."
OP_WHY = "Test: drone is hovering over the base."
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


def answer(run_dir: Path, data: dict) -> None:
    tmp = run_dir / "answer.json.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, run_dir / "answer.json")


def texts(at) -> str:
    parts = [m.value for m in at.markdown] + [m.value for m in at.caption]
    for kind in (at.info, at.warning, at.error, at.success):
        parts += [m.value for m in kind]
    return "\n".join(parts)


def labels(at) -> list[str]:
    return [b.label for b in at.button]


def page(view: str) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    if view != "Operator":
        at.radio[0].set_value(view).run()
    return at


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"Temp runs folder: {TMP}")
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "pipeline.py"), "--event", "07", "--steps", "6,7", "--dry-run",
         "--web", "--dry-reject", "7"],
        cwd=str(HERE), env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    try:
        run_dir = wait_for(lambda: next((d for d in TMP.iterdir() if d.is_dir()), None), "the run folder")

        # ---- step 6: operator asks for more than recommended -> control room STOPs ----
        req = pending(run_dir, "operator", 6)
        answer(run_dir, {"id": req["id"], "decision": "override", "reason": OP_WHY,
                         "override_action": {"rung": 3, "action": "RF jammer (D-JAM) against T-1"}})
        req = pending(run_dir, "control_room", 6)

        cr = page("Control room")
        t, b = texts(cr), labels(cr)
        check(not cr.exception, "control-room page loads with a request waiting")
        check("Control-room decision needed" in t, "control-room panel shown")
        check("Silence means no" not in t and "Deadline" not in t, "no countdown / deadline shown")
        check("• Safety agent: CONCUR" in t, "safety agent's call in bold next to the buttons")
        check("full concerns and override assessment" in t, "pointer to the safety details")
        check("Approve: RUNG 3 — RF jammer" in b, "Approve button names the rung: 'Approve: RUNG 3 — RF jammer'")
        check(STOP in b, "STOP button shown")
        check("stronger action than recommended" in t and OP_WHY in t,
              "operator's stronger-action request and reason shown")
        check("Control-room only information now" in t and "C-04" in t, "control-room-only info shown above the buttons")

        op = page("Operator")
        t = texts(op)
        check(STOP not in labels(op) and not any(l.startswith("Approve") for l in labels(op)),
              "operator view: no control-room buttons")
        check("Safety agent" not in t and "Safer alternative" not in t and "Control-room only" not in t and "C-04" not in t,
              "operator view: no safety advice, no control-room-only info")
        check("went to the control room" in t, "operator view: 'went to the control room'")

        next(x for x in cr.button if x.label == STOP).click().run()
        time.sleep(1)
        check("A written reason is required to stop" in texts(cr), "STOP with no reason: refused on the page")
        check(not (run_dir / "answer.json").exists(), "STOP with no reason: nothing sent")
        check(json.loads((run_dir / "pending.json").read_text(encoding="utf-8"))["id"] == req["id"],
              "pipeline still waiting on the same control-room request")
        cr.text_area(key=f"stop-reason-{req['id']}").input(STOP_WHY)
        next(x for x in cr.button if x.label == STOP).click().run()
        check(STOP not in labels(cr), "STOP with a reason: sent, buttons gone")

        # ---- step 7: the control room stopped rung 3 at step 6, so the escalation guardrail
        #      blocks rung 3 now and refuses the operator's override (nothing reaches the control room) ----
        req = pending(run_dir, "operator", 7)
        check(req["shown"]["blocked_by"] == "guardrail", "step 7: operator sees DO NOT ENGAGE from the GUARDRAIL")
        answer(run_dir, {"id": req["id"], "decision": "override", "reason": OP_WHY})
        out, _ = proc.communicate(timeout=120)
        check(proc.returncode == 0, f"pipeline exited cleanly (code {proc.returncode})")
        rows = [json.loads(l) for l in (run_dir / "detail.jsonl").read_text(encoding="utf-8").splitlines()]
        crs = {r["step"]: r["decision"] for r in rows if r["kind"] == "control_room_decision"}
        ends = {r["step"]: r for r in rows if r["kind"] == "step_end"}
        check(crs[6]["decision"] == "stop" and crs[6]["reason"] == STOP_WHY and crs[6]["source"] == "web",
              "log: step 6 web STOP with the typed reason")
        check(ends[6]["outcome"].startswith("NOT APPROVED (stop)") and ends[6]["final_rung"] == 2,
              f"log: step 6 outcome {ends[6]['outcome']}")
        check(7 not in crs and any(r["kind"] == "guardrail_override_refused" and r["step"] == 7 for r in rows),
              "log: step 7 override refused by the guardrail; nothing sent to the control room")
        check(not [r for r in rows if r["kind"] == "web_answer_rejected"], "log: no answers rejected by the pipeline")
    finally:
        if proc.poll() is None:
            proc.kill()

    # ---- a fresh run, step 7 only: reviewer rejected, operator overrides -> side by side -> APPROVE ----
    first = run_dir
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "pipeline.py"), "--event", "07", "--steps", "7", "--dry-run",
         "--web", "--dry-reject", "7"],
        cwd=str(HERE), env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    try:
        run_dir = wait_for(lambda: next((d for d in TMP.iterdir() if d.is_dir() and d != first), None),
                           "the second run folder")
        req = pending(run_dir, "operator", 7)
        answer(run_dir, {"id": req["id"], "decision": "override", "reason": OP_WHY})
        req = pending(run_dir, "control_room", 7)
        cr = page("Control room")
        t = texts(cr)
        check("OPERATOR OVERRODE REVIEWER" in t, "flag: OPERATOR OVERRODE REVIEWER")
        check("Reviewer's reasons (REJECT)" in t and "--dry-reject" in t and "Operator's reason" in t and OP_WHY in t,
              "reviewer's and operator's reasons side by side")
        cr.button(key=f"approve-{req['id']}").click().run()
        check(f"approve-{req['id']}" not in [x.key for x in cr.button], "Approve: sent, buttons gone")
        out, _ = proc.communicate(timeout=120)
        check(proc.returncode == 0, f"second pipeline exited cleanly (code {proc.returncode})")
        rows = [json.loads(l) for l in (run_dir / "detail.jsonl").read_text(encoding="utf-8").splitlines()]
        crs = {r["step"]: r["decision"] for r in rows if r["kind"] == "control_room_decision"}
        ends = {r["step"]: r for r in rows if r["kind"] == "step_end"}
        check(crs[7]["decision"] == "approve" and crs[7]["source"] == "web", "log: step 7 web APPROVE")
        check(ends[7]["outcome"].startswith("APPROVED: rung 3"), f"log: step 7 outcome {ends[7]['outcome']}")
    finally:
        if proc.poll() is None:
            proc.kill()

    # ---- a request with no safety advice (no pipeline needed) ----
    fake = TMP / "99999999-999999-event-07-dryrun"
    fake.mkdir()
    (fake / "detail.jsonl").write_text(
        json.dumps({"kind": "run_start", "event": "07", "dry_run": True, "humans": "web"}) + "\n" +
        json.dumps({"kind": "step_start", "step": 7, "now": "2026-12-03 08:22:00"}) + "\n", encoding="utf-8")
    (fake / "pending.json").write_text(json.dumps(
        {"id": "late", "role": "control_room", "step": 7, "now": "2026-12-03 08:22:00",
         "choices": ["approve", "stop"], "do_not_engage": False,
         "requested_rung": 3, "requested_action": "RF jammer", "operator": {"decision": "accept"},
         "advice": None}), encoding="utf-8")
    cr = page("Control room")
    check("NO SAFETY ADVICE AVAILABLE" in texts(cr), "no advice: 'NO SAFETY ADVICE AVAILABLE' shown")
    check("• Safety agent" not in texts(cr), "no advice: no safety bullet")
    cr.button(key="approve-late").click().run()
    sent = json.loads((fake / "answer.json").read_text(encoding="utf-8")) if (fake / "answer.json").exists() else {}
    check(sent.get("decision") == "approve", "no advice: Approve still works (request passes through, ROE-4.5)")

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
