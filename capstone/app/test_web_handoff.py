"""Test the --web decision handoff with a DRY RUN (no API calls, $0).

Run (from the repository folder, GBUS-652-Coursework):
    .venv\\Scripts\\python.exe capstone\\app\\test_web_handoff.py

The pipeline runs in its own process with FGB_RUNS_DIR pointed at a temporary folder, so the
real runs/ folder and runs/run-index.csv are never touched. This script plays the web page:
it waits for pending.json and writes answer.json.

Script (event 07, steps 6 and 7; the dry-run analyst says rung 2 at step 6 and rung 3 at step 7):
  step 6 operator:      bad answers first (wrong id; override without a reason) -> must be ignored,
                        then OVERRIDE to rung 3 with a reason -> goes to the control room
  step 6 control room:  APPROVE
  step 7 operator:      ACCEPT (rung 3 -> control room)
  step 7 control room:  silent for a few seconds -> must STILL be waiting (no time limit),
                        then STOP with a reason
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUIET_SECONDS = 4       # the control room stays silent this long; the pipeline must keep waiting

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


def read_pending(run_dir: Path, role: str, step: int) -> dict:
    def ok():
        p = run_dir / "pending.json"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return d if d["role"] == role and d["step"] == step else None
    return wait_for(ok, f"step {step} {role} request")


def answer(run_dir: Path, data: dict) -> None:
    tmp = run_dir / "answer.json.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, run_dir / "answer.json")


def wait_answer_taken(run_dir: Path) -> None:
    wait_for(lambda: not (run_dir / "answer.json").exists(), "the pipeline to read answer.json", 10)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = Path(tempfile.mkdtemp(prefix="fgb-web-test-"))
    env = {**os.environ, "FGB_RUNS_DIR": str(tmp), "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, str(HERE / "pipeline.py"), "--event", "07", "--steps", "6,7",
           "--dry-run", "--web"]
    print(f"Temp runs folder: {tmp}")
    proc = subprocess.Popen(cmd, cwd=str(HERE), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    try:
        run_dir = wait_for(lambda: next((d for d in tmp.iterdir() if d.is_dir()), None), "the run folder")
        print(f"Run folder: {run_dir.name}\n")

        # Step 6, operator
        req = read_pending(run_dir, "operator", 6)
        check(req["choices"] == ["accept", "reject", "override"], "operator gets accept/reject/override")
        check("deadline" not in req, "operator request has no deadline")
        check("advice" not in req, "operator request carries no safety advice")
        check(req["shown"]["recommended_rung"] == 2, "operator sees the rung 2 recommendation")
        answer(run_dir, {"id": "wrong-id", "decision": "accept"})
        wait_answer_taken(run_dir)
        answer(run_dir, {"id": req["id"], "decision": "override", "reason": "  "})
        wait_answer_taken(run_dir)
        time.sleep(1)
        check((run_dir / "pending.json").exists(), "bad answers are ignored; still waiting")
        answer(run_dir, {"id": req["id"], "decision": "override",
                         "reason": "Test: I want the jammer ready.",
                         "override_action": {"rung": 3, "action": "RF jammer (D-JAM) against T-1"}})

        # Step 6, control room
        req = read_pending(run_dir, "control_room", 6)
        check(req["choices"] == ["approve", "stop"], "control room gets approve/stop")
        check("deadline" not in req, "control-room request has no deadline")
        check(req["operator"]["decision"] == "override" and req["requested_rung"] == 3,
              "control room sees the operator's override and rung 3 request")
        check(req["advice"] is not None and req["advice"]["advice"] == "CONCUR",
              "control room sees the safety advice")
        answer(run_dir, {"id": req["id"], "decision": "approve"})

        # Step 7, operator accepts rung 3; control room stays silent for a while, then STOPs
        req = read_pending(run_dir, "operator", 7)
        answer(run_dir, {"id": req["id"], "decision": "accept"})
        req = read_pending(run_dir, "control_room", 7)
        print(f"  ...  staying silent for the step 7 control room ({QUIET_SECONDS} s)")
        time.sleep(QUIET_SECONDS)
        check(proc.poll() is None and (run_dir / "pending.json").exists(),
              f"after {QUIET_SECONDS} s of silence the pipeline is still waiting (no time limit)")
        answer(run_dir, {"id": req["id"], "decision": "stop", "reason": "Test: walkers on the beach."})

        out, _ = proc.communicate(timeout=120)
        check(proc.returncode == 0, f"pipeline exited cleanly (code {proc.returncode})")

        rows = [json.loads(l) for l in (run_dir / "detail.jsonl").read_text(encoding="utf-8").splitlines()]
        start = rows[0]
        check(start["humans"] == "web" and "cr_timeout_s" not in start, "run_start logs humans=web, no timeout")
        rej = [r for r in rows if r["kind"] == "web_answer_rejected"]
        check(len(rej) == 2, f"two bad answers logged as rejected ({len(rej)})")
        ops = {r["step"]: r for r in rows if r["kind"] == "operator_decision"}
        crs = {r["step"]: r for r in rows if r["kind"] == "control_room_decision"}
        check(ops[6]["decision"]["decision"] == "override" and ops[6]["decision"]["source"] == "web"
              and ops[6]["requested_rung"] == 3, "step 6 operator: web override to rung 3 logged")
        check(ops[6]["decision"]["reason"] == "Test: I want the jammer ready.", "override reason logged")
        check(crs[6]["decision"]["decision"] == "approve", "step 6 control room: approve logged")
        check(ops[7]["decision"]["decision"] == "accept", "step 7 operator: accept logged")
        check(crs[7]["decision"]["decision"] == "stop" and crs[7]["decision"]["reason"] == "Test: walkers on the beach.",
              "step 7 control room: stop with its reason logged")
        ends = {r["step"]: r for r in rows if r["kind"] == "step_end"}
        check(ends[6]["outcome"].startswith("APPROVED: rung 3"), f"step 6 outcome: {ends[6]['outcome']}")
        check(ends[7]["outcome"].startswith("NOT APPROVED (stop)") and ends[7]["final_rung"] == 2,
              f"step 7 outcome: {ends[7]['outcome']}")
        check(not (run_dir / "pending.json").exists() and not (run_dir / "answer.json").exists(),
              "no pending.json / answer.json left behind")
        check((tmp / "run-index.csv").exists(), "run-index row written to the TEMP folder, not runs/")

        print("\n--- pipeline output (last 14 lines) ---")
        print("\n".join(out.strip().splitlines()[-14:]))
    finally:
        if proc.poll() is None:
            proc.kill()

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
