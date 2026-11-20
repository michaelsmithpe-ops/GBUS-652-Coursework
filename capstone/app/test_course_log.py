"""Test the course run log, runs/log.jsonl (one line per REAL run, exactly 7 fields). $0, no API calls.

Run (from the repository folder, GBUS-652-Coursework):
    .venv\\Scripts\\python.exe capstone\\app\\test_course_log.py

FGB_RUNS_DIR points at a temporary folder, so the real runs/ folder is never touched.
  Part 1: steps_label and run_output give the right text (complete, no control room, analyst
          failed, incomplete, nothing finished).
  Part 2: write_course_log appends one line per call with exactly the 7 required fields, and
          input_tokens = uncached + cache read + cache write.
  Part 3: a DRY RUN (subprocess) writes its own runs/<id>/ folder and run-index row but does NOT
          write runs/log.jsonl; its usage records carry seconds = 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="fgb-course-log-"))
os.environ["FGB_RUNS_DIR"] = str(TMP)
sys.path.insert(0, str(HERE))
import pipeline as P   # noqa: E402  (after FGB_RUNS_DIR is set)

FIELDS = ["timestamp", "model", "input", "output", "input_tokens", "output_tokens", "seconds"]
failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        failures.append(label)


print(f"Temp runs folder: {TMP}\n\nPart 1: labels and output text")
check(P.steps_label([1, 2, 3, 4, 5, 6, 7]) == "1-7", "all 7 steps -> '1-7'")
check(P.steps_label([7]) == "7", "last step -> '7'")
check(P.steps_label([1, 4, 7]) == "1,4,7", "chosen steps -> '1,4,7'")
check(P.steps_label([3, 4]) == "3-4", "two in a row -> '3-4'")

full = {"outcome": "APPROVED: rung 4 - jam", "shown": "jam", "operator": "accept",
        "control_room": "approve", "final_rung": 4}
out = P.run_output([6, 7], [(6, {"outcome": "x"}), (7, full)])
print("        ", out)
check(out == "Step 7: APPROVED: rung 4 - jam. Shown to operator: jam. Operator: ACCEPT. "
             "Control room: APPROVE.", "complete run with control room")
low = {"outcome": "Operator authority: rung 2 - track", "shown": "track", "operator": "accept",
       "control_room": None}
check(P.run_output([7], [(7, low)]).endswith("Control room: not needed."), "no control room -> 'not needed'")
failed = {"outcome": "analyst failed", "final_rung": 1}
check(P.run_output([7], [(7, failed)]) == "Step 7: analyst failed.", "analyst failed -> outcome only")
inc = P.run_output([1, 2, 3], [(1, low)])
check(inc.startswith("INCOMPLETE (1 of 3 steps finished). Step 1:"), "stopped early -> INCOMPLETE prefix")
check(P.run_output([1, 2], []) == "INCOMPLETE: no step finished (0 of 2).", "nothing finished")

print("\nPart 2: write_course_log")
total = {"calls": 9, "in": 1000, "out": 500, "cache_read": 20000, "cache_write": 3000, "seconds": 41.26}
seven = [(s, low) for s in range(1, 7)] + [(7, full)]
P.write_course_log("07", list(range(1, 8)), total, seven)
P.write_course_log("07", list(range(1, 8)), total, seven)
lines = (TMP / "log.jsonl").read_text(encoding="utf-8").splitlines()
check(len(lines) == 2, "two calls -> two lines (appends, never overwrites)")
row = json.loads(lines[0])
print("        ", lines[0])
check(list(row) == FIELDS, "exactly the 7 fields, in order")
check(row["model"] == "claude-sonnet-5-5", "model")
check(row["input"] == "event 07, steps 1-7", "input")
check(row["output"].startswith("Step 7: APPROVED"), "output = last step's outcome (no INCOMPLETE)")
check(row["input_tokens"] == 24000, "input_tokens = 1000 + 20000 + 3000")
check(row["output_tokens"] == 500, "output_tokens")
check(row["seconds"] == 41.3, "seconds rounded to 0.1")
check(isinstance(row["input_tokens"], int) and isinstance(row["seconds"], float), "number types")
(TMP / "log.jsonl").unlink()

print("\nPart 3: a dry run does not write runs/log.jsonl")
r = subprocess.run([sys.executable, str(HERE / "pipeline.py"), "--event", "07", "--steps", "last", "--dry-run"],
                   capture_output=True, text=True, encoding="utf-8", env=os.environ.copy(), timeout=180)
check(r.returncode == 0, "dry run exits cleanly" + ("" if r.returncode == 0 else f": {r.stderr[-400:]}"))
check(not (TMP / "log.jsonl").exists(), "no runs/log.jsonl after a dry run")
check((TMP / "run-index.csv").exists(), "run-index.csv still written")
run_dirs = [d for d in TMP.iterdir() if d.is_dir()]
check(len(run_dirs) == 1 and (run_dirs[0] / "detail.jsonl").exists(), "per-run detail.jsonl still written")
check(bool(run_dirs) and not (run_dirs[0] / "log.jsonl").exists(), "run folder has NO log.jsonl (only runs/log.jsonl is the course log)")
if run_dirs:
    rows = [json.loads(l) for l in (run_dirs[0] / "detail.jsonl").read_text(encoding="utf-8").splitlines()]
    end = [x for x in rows if x["kind"] == "run_end"]
    check(bool(end) and end[0]["usage"].get("seconds") == 0.0, "dry-run usage has seconds = 0")

print(f"\n{'ALL PASS' if not failures else f'{len(failures)} FAILED'}"
      f" ({sum(1 for _ in failures)} failures)")
sys.exit(1 if failures else 0)
