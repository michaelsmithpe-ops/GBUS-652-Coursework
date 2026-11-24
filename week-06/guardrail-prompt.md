# Guardrail Prompt

```text
Goal: add one guardrail to the Fort GBUS Counter-Drone Decision Aid that enforces, in code and not
in a prompt, the rule the tool must never break: never escalate beyond what is allowed. Then run
the evaluation again so I can compare it with eval-1.

Tell me your plan before you write any code, and keep it to what this job needs.

1. What it checks. Create capstone/app/guardrail.py. It is an OUTPUT guardrail: it runs AFTER the
   analyst and reviewer agents, and BEFORE anything is shown to the operator or sent to the control
   room. It checks the analyst's recommendation against two rules:
   (a) Ladder (ROE-4.1): the recommended rung may not be higher than the analyst's own threat level
       allows. Read the ladder table from capstone/inputs/roe-standing.md; don't copy it into code.
   (b) Stop means stop (ROE-4.4): once the control room STOPS a request at rung N, nothing at rung N
       or higher goes forward for the rest of that event. eval-1's T10 showed why: after the control
       room stopped the interceptor, the analyst asked for the laser next, and the reviewer approved it.

2. What happens when it trips:
   - The operator sees DO NOT ENGAGE with a reason that starts with GUARDRAIL and names the rule.
   - An operator override cannot send a blocked rung up: the override is refused, and nothing goes
     to the control room.
   - Every check, and every time it trips, is recorded in the run log.

3. Warnings only (shown and logged, never blocking): the recommended defeat option is down or not
   reporting in the health status; laser or gun is recommended but no track has positive visual ID
   (ROE-4.7); a cited ROE, notice, or health ID does not exist in the input files. A warning must
   never stop a run.

4. Wire it into capstone/app/pipeline.py, show it on the web page (capstone/app/viewer.py), and have
   week-06/evaluate.py report where the guardrail stepped in.

5. Test it for free first:
   - Add a dry-run option that makes the canned analyst recommend the gun at threat LOW, and write
     capstone/app/test_guardrail.py to check each rule, the override refusal, and the warnings.
   - Make sure every existing test still passes.

6. Then, only when I say so, run the evaluation again with the same test cases and save it to
   week-06/runs/eval-2.txt, in the same pinned format as eval-1 (one line per case: id, then PASS,
   or FAIL and a reason; last line Passed: N of M). Don't edit the saved files.

7. My API key rule: the tool reads the key only from API-Key.txt in the folder above my repository.
   Never write the key to any file, log, or output.
```
