"""Test the viewer's 'Start a run' control. DRY RUNS ONLY (no API calls, $0).

Run (from the repository folder, GBUS-652-Coursework):
    .venv\\Scripts\\python.exe capstone\\app\\test_viewer_start.py

Uses a temporary runs folder (FGB_RUNS_DIR); the real runs/ and run-index.csv are untouched.
The REAL-run button is NEVER clicked: the test only checks that it is disabled until the
confirm box is ticked, and that it shows a cost estimate.
  1. Start a dry run from the page: event 07, step 6 only, dry-run reviewer rejects at 6
  2. The page switches to the live run and shows DO NOT ENGAGE + the operator buttons
  3. Reject it on the page; the run ends; the log has the settings chosen on the page
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fgb-viewer-start-"))
os.environ["FGB_RUNS_DIR"] = str(TMP)          # must be set before the page is loaded

from streamlit.testing.v1 import AppTest      # noqa: E402

HERE = Path(__file__).resolve().parent
PAGE = str(HERE / "viewer.py")
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
        time.sleep(0.3)
    raise TimeoutError(f"timed out waiting for {what}")


def texts(at) -> str:
    parts = [m.value for m in at.markdown] + [m.value for m in at.caption]
    for kind in (at.info, at.warning, at.error, at.success):
        parts += [m.value for m in kind]
    return "\n".join(parts)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"Temp runs folder: {TMP}")
    # A fake past real run in the temp index, so the cost estimate has something to average.
    (TMP / "run-index.csv").write_text(
        "run_id,event,steps,dry_run,prompts,model,model_calls,input_tokens,cache_read,cache_write,"
        "output_tokens,cost_usd,final_rung,final_outcome,code_grade,human_grade,human_notes\n"
        "fake-real,07,1 2,FALSE,v1/x,m,0,0,0,0,0,0.5000,2,x,,,\n", encoding="utf-8")

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    check(not at.exception, "page loads with no live run")
    check(at.checkbox(key="start-dry").value is True, "'Dry run' is ticked by default")
    labels = [b.label for b in at.button]
    check(any(l.startswith("Start DRY RUN") for l in labels), "Start DRY RUN button shown")
    check(not any(l.startswith("Start REAL") for l in labels), "no REAL button while 'Dry run' is ticked")

    # REAL: look, never click
    at.checkbox(key="start-dry").uncheck().run()
    real = at.button(key="start-real-btn")
    check(real.disabled, "REAL button disabled until the confirm box is ticked")
    check("calls the Claude API and costs money" in texts(at) and "$0.25 per step" in texts(at),
          "REAL warning with a cost estimate ($0.25/step from the index)")
    at.checkbox(key="start-confirm").check().run()
    check(not at.button(key="start-real-btn").disabled, "REAL button enabled after confirm (NOT clicked)")
    at.checkbox(key="start-confirm").uncheck().run()
    at.checkbox(key="start-dry").check().run()

    # 1. start a dry run from the page
    at.selectbox(key="start-event").select("07").run()
    at.radio(key="start-which").set_value("Choose").run()
    at.multiselect(key="start-chosen").set_value([6]).run()
    at.multiselect(key="start-reject").set_value([6]).run()
    b = at.button(key="start-dry-btn")
    check(b.label == "Start DRY RUN: event 07, 1 step(s)", f"button label: {b.label}")
    b.click().run()
    check("Starting the run" in texts(at), "'Starting the run…' shown")

    run_dir = wait_for(lambda: next((d for d in TMP.iterdir() if d.is_dir() and (d / "pending.json").exists()), None),
                       "the run to ask the operator")
    check(run_dir.name.endswith("-event-07-dryrun"), f"a DRY run was started: {run_dir.name}")

    # 2. the page follows it
    at.run()
    t = texts(at)
    check("LIVE" in t and "DO NOT ENGAGE" in t, "page switched to the live run: DO NOT ENGAGE shown")
    check(not [x for x in at.button if x.key == "start-dry-btn"], "Start control hidden while a run is live")

    # 3. reject on the page
    req = json.loads((run_dir / "pending.json").read_text(encoding="utf-8"))
    at.button(key=f"reject-{req['id']}").click().run()
    wait_for(lambda: '"run_end"' in (run_dir / "detail.jsonl").read_text(encoding="utf-8"), "the run to end", 60)
    rows = [json.loads(l) for l in (run_dir / "detail.jsonl").read_text(encoding="utf-8").splitlines()]
    start = rows[0]
    check(start["dry_run"] is True and start["humans"] == "web", "log: dry run, humans=web")
    check(start["steps"] == [6] and start["dry_reject"] == [6], "log: steps [6], reviewer rejects [6] (as chosen)")
    op = next(r for r in rows if r["kind"] == "operator_decision")
    check(op["decision"]["decision"] == "reject" and op["decision"]["source"] == "web", "log: web reject")
    check((TMP / "launcher.log").exists() and "DRY RUN: event 07, steps 6" in (TMP / "launcher.log").read_text(encoding="utf-8"),
          "launcher.log records the start")
    time.sleep(1.5)
    at.run()
    check(any(x.key == "start-dry-btn" for x in at.button), "Start control back after the run ends")
    check("finished" in texts(at) and "selected below for replay" in texts(at), "page says the run finished, kept for replay")
    check(at.selectbox(key="event").value == "07", f"page STAYS on event 07 (not 01): {at.selectbox(key='event').value}")
    check(at.checkbox(key="incl-dry").value is True, "'Include dry runs' turned on for a finished dry run")
    check(at.selectbox(key="replay-run").value == run_dir.name, f"finished run selected for replay: {at.selectbox(key='replay-run').value}")
    check(at.select_slider(key="time").value == "2026-12-03 08:21:40", f"slider on the run's last step: {at.select_slider(key='time').value}")
    t = texts(at)
    check("DO NOT ENGAGE" in t and "**Operator** (web): **REJECT**" in t, "the finished run's decisions are on screen")
    at.run()
    check(at.selectbox(key="event").value == "07" and at.selectbox(key="replay-run").value == run_dir.name,
          "still on the finished run after another redraw")

    # Safety: nothing but dry runs was ever started
    dirs = [d.name for d in TMP.iterdir() if d.is_dir()]
    check(all(d.endswith("-dryrun") for d in dirs), f"only dry runs in the temp folder: {dirs}")

    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
