"""Smoke-test the viewer page for every event, both views, first and last moment. No API calls.

Run:  .venv\\Scripts\\python.exe capstone\\app\\test_viewer.py
"""

import csv
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

PAGE = str(Path(__file__).resolve().parent / "viewer.py")
RUNS = Path(__file__).resolve().parent.parent / "runs"
problems, checked = [], 0

# Events that have a real (non-dry) saved run: the page MUST offer a replay for them.
expect_runs = set()
if (RUNS / "run-index.csv").exists():
    with open(RUNS / "run-index.csv", newline="", encoding="utf-8") as f:
        expect_runs = {r["event"].strip().zfill(2) for r in csv.DictReader(f)
                       if r["dry_run"].strip().lower() == "false" and (RUNS / r["run_id"]).exists()}

for view in ("Operator", "Control room"):
    for event in [f"{i:02d}" for i in range(1, 12)]:
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        at.radio[0].set_value(view).run()
        at.selectbox[0].select(event).run()
        slider = at.select_slider[0]
        for t in (slider.options[0], slider.options[-1]):
            slider.set_value(t).run()
            checked += 1
            if at.exception:
                problems.append(f"{view} / event {event} / {t}: {at.exception[0].message}")
        replay = [s for s in at.selectbox if s.key == "replay-run"]
        has_replay = bool(replay) and len(replay[0].options) > 1
        if event in expect_runs and not has_replay:
            problems.append(f"{view} / event {event}: saved run in run-index.csv but no replay offered")
        if has_replay:                                                      # a saved run exists
            at.selectbox(key="replay-run").select_index(1).run()
            slider = at.select_slider[0]
            slider.set_value(slider.options[-1]).run()
            checked += 1
            text = " ".join(m.value for m in at.markdown)
            if at.exception:
                problems.append(f"{view} / event {event} / saved run: {at.exception[0].message}")
            elif "Operator" not in text:
                problems.append(f"{view} / event {event} / saved run: decision chain not shown")
            infos = " ".join(w.value for w in at.warning)
            if view == "Operator" and "C-0" in infos:
                problems.append(f"Operator view / event {event}: CONTROL-ROOM INFO LEAKED")
            if view == "Operator" and ("Safer alternative" in text or "Safety agent" in infos):
                problems.append(f"Operator view / event {event}: SAFETY ADVICE LEAKED")
            if "RUNG" not in text and "DO NOT ENGAGE" not in text:
                problems.append(f"{view} / event {event} / saved run: no quick RUNG label")
            if "Analyst's recommendation" not in " ".join(i.value for i in at.info):
                problems.append(f"{view} / event {event} / saved run: analyst label missing")
            print(f"  saved run shown for event {event} ({view} view)")

print(f"{checked} page states checked; {len(problems)} problems")
for p in problems:
    print("  PROBLEM:", p)
sys.exit(1 if problems else 0)
