# Week 6: Evaluation and guardrail (Fort GBUS capstone)

The tool tested is the capstone, [Fort GBUS](../capstone/). The results are already saved, so
nothing needs to be run to grade this week:

- Test cases: [`test-cases.csv`](test-cases.csv) (11 cases, one per drone event, steps 1-7)
- Evaluation program: [`evaluate.py`](evaluate.py)
- Results: [`runs/eval-1.txt`](runs/eval-1.txt) (before the guardrail) and `runs/eval-2.txt` (after)
- Prompts: [`prompts.md`](prompts.md); writeup: [`writeup.md`](writeup.md)

The [`alder-creek/`](alder-creek/) folder is the separate lecture example and is not part of
Fort GBUS.

## How to run the evaluation (free)

On Windows with Python 3.13, from the repository folder:

1. Double-click [`capstone/run.bat`](../capstone/run.bat) once. It creates `.venv`, installs the
   packages, and builds the rules database. Close the web page it opens.
2. Run every case with canned answers. This never calls Claude and saves no evaluation results
   (the tool keeps its dry-run folders under `capstone/runs/`):

   ```
   .venv\Scripts\python.exe week-06\evaluate.py --dry-run
   ```

   The canned answers are placeholders, so every case FAILs (`Passed: 0 of 11`). The dry run
   shows the evaluation working end to end (pipeline, code grading, guardrail), not Claude's
   answers. Add `--cases T07,T11` to run only some cases.

A real evaluation (`--out NAME`) calls Claude for all 11 cases (about $16). It needs your own
Anthropic API key in `API-Key.txt` in the folder above the repository; without that file no
case can call Claude.
