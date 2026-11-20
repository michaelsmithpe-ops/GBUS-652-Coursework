"""Fort GBUS counter-drone pipeline: analyst -> reviewer -> operator -> safety agent -> control room.

Usage (from the repository folder, GBUS-652-Coursework; python = .venv\\Scripts\\python.exe):
    python capstone\\app\\pipeline.py --event 07 --dry-run          # no API calls
    python capstone\\app\\pipeline.py --event 07 --steps last       # ONE real step
    python capstone\\app\\pipeline.py --event 07                    # all 7 steps
    python capstone\\app\\pipeline.py --event 07 --interactive      # you make the human decisions
    python capstone\\app\\pipeline.py --event 07 --web --dry-run    # decisions on the web page

Workflow (a fixed pipeline; code decides the order, not a model):
  For each chosen step (readings arrive every 20 s; 7 steps per event):
    1. Write the clock file (event, now). Every MCP tool refuses later times.
    2. ANALYST agent (Claude, MCP tools) -> submit_assessment.
    3. REVIEWER agent (Claude, same tools, sees the analyst's full output) -> submit_review.
       REJECT => what the operator sees becomes DO NOT ENGAGE (ROE-4.2).
    4. OPERATOR (human; --web buttons, --interactive, or SIMULATED from decisions.json):
       accept / reject / override.
    5. If the requested action needs the control room (rung 3+ or an override):
       SAFETY agent (Claude, + control-room tool) -> submit_advice (advises only; ROE-4.5).
       If the safety agent fails, the request passes through marked NO SAFETY ADVICE AVAILABLE.
    6. CONTROL ROOM (human; --web, --interactive or SIMULATED): approve / stop / no response (= no).
       --web: the control room, like the operator, has no time limit; nothing is carried out
       until a person clicks Approve (no approval = no action, ROE-1.6).
  Everything is logged to runs/<run-id>/ : detail.jsonl (every step, every agent, every tool call,
  tokens, cost) and summary.md, plus one row in runs/run-index.csv (grade column left for you).
  REAL runs (not dry runs) also append ONE line to runs/log.jsonl, the course run log, with exactly
  timestamp, model, input, output, input_tokens, output_tokens, seconds (totals over every Claude
  call in the run; input_tokens includes cached tokens; seconds = time spent waiting on Claude,
  not on people). Only this program writes that file; never edit it by hand.

Model: claude-sonnet-5-5 with the server-side refusal fallback (as in week 5). System prompts are
prompts/shared.txt + the role file, cached. The API key is read ONLY from API-Key.txt in the
folder above the repository, at run time, and is never printed, logged, or written to any file.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import hashlib
import json
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import fgb_data as D
from output_tools import SUBMIT_ADVICE, SUBMIT_ASSESSMENT, SUBMIT_REVIEW

HERE = Path(__file__).resolve().parent                  # .../GBUS-652-Coursework/capstone/app
ROOT = HERE.parent                                      # .../GBUS-652-Coursework/capstone
PROMPTS = ROOT / "prompts"
RUNS = Path(os.environ.get("FGB_RUNS_DIR") or ROOT / "runs")   # tests point this at a temp folder
SERVER = HERE / "fgb_mcp_server.py"
KEY_FILE = ROOT.parent.parent / "API-Key.txt"           # GBUS-652-Course/API-Key.txt (above the repo)
DECISIONS_FILE = HERE / "decisions.json"

MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_CALLS = 20                                     # per agent per step
STEP_SECONDS = 20
STEPS_PER_EVENT = 7
CONTROL_ROOM_RUNG = 3                                   # ROE-4.1: rung 3+ needs the control room
DRY_REJECT_STEPS: set[int] = set()                      # --dry-reject: dry-run reviewer says REJECT here

# USD per million tokens for claude-sonnet-5-5 (cached 2026-11-03; verify before the business case).
PRICE = {"in": 2.00, "out": 10.00, "cache_read": 0.10, "cache_write": 2.50}

ROLES = {
    "analyst":  {"prompt": "analyst.txt",  "server_role": "analyst",  "submit": SUBMIT_ASSESSMENT},
    "reviewer": {"prompt": "reviewer.txt", "server_role": "reviewer", "submit": SUBMIT_REVIEW},
    "safety":   {"prompt": "safety.txt",   "server_role": "safety",   "submit": SUBMIT_ADVICE},
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def jdump(x) -> str:
    return json.dumps(x, ensure_ascii=False, indent=2)


def preview(text: str, n: int = 160) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= n else one[:n] + "..."


def cost_of(u: dict) -> float:
    return (u["in"] * PRICE["in"] + u["out"] * PRICE["out"] + u["cache_read"] * PRICE["cache_read"]
            + u["cache_write"] * PRICE["cache_write"]) / 1_000_000


def new_usage() -> dict:
    return {"calls": 0, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "seconds": 0.0}


def add_usage(total: dict, part: dict) -> None:
    for k in total:
        total[k] += part.get(k, 0)


def prompt_version() -> dict:
    files = ["shared.txt", "analyst.txt", "reviewer.txt", "safety.txt"]
    h = hashlib.sha256(b"".join((PROMPTS / f).read_bytes() for f in files)).hexdigest()[:10]
    return {"version": (PROMPTS / "version.txt").read_text(encoding="utf-8").strip(), "hash": h}


def system_prompt(role: str) -> list:
    text = (PROMPTS / "shared.txt").read_text(encoding="utf-8").strip() + "\n\n" + \
           (PROMPTS / ROLES[role]["prompt"]).read_text(encoding="utf-8").strip()
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def load_api_key() -> str:
    """Read the key from API-Key.txt only (course rule). Never print, log, or save it."""
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        sys.exit(f"Could not read the API key file {KEY_FILE}.")
    if not key:
        sys.exit("The API key is empty.")
    return key


def event_steps(event_id: str) -> list[str]:
    with open(ROOT / "inputs" / "events.csv", newline="", encoding="utf-8") as f:
        times = sorted({r["Timestamp"] for r in csv.DictReader(f) if r["Event ID"] == event_id})
    if not times:
        sys.exit(f"No event {event_id} in events.csv.")
    return times


def choose_steps(spec: str, n: int) -> list[int]:
    if spec == "all":
        return list(range(1, n + 1))
    if spec == "last":
        return [n]
    try:
        steps = sorted({int(s) for s in spec.split(",")})
    except ValueError:
        sys.exit("--steps must be 'all', 'last', or numbers like 1,4,7")
    if not all(1 <= s <= n for s in steps):
        sys.exit(f"Steps must be between 1 and {n}.")
    return steps


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------
class RunLog:
    def __init__(self, event_id: str, dry_run: bool):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_id = f"{stamp}-event-{event_id}" + ("-dryrun" if dry_run else "")
        self.dir = RUNS / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = open(self.dir / "detail.jsonl", "w", encoding="utf-8")
        self.lines: list[str] = []

    def record(self, kind: str, **data) -> None:
        row = {"time": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind, **data}
        self.jsonl.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self.jsonl.flush()

    def say(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def close(self) -> None:
        self.jsonl.close()
        (self.dir / "summary.md").write_text("\n".join(self.lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# One agent turn: Claude + MCP tools until it calls its submit tool
# ---------------------------------------------------------------------------
async def run_agent(role: str, session: ClientSession, mcp_tools: list, client, user_msg: str,
                    log: RunLog, step: int, dry_run: bool) -> tuple[dict | None, str, dict]:
    """Returns (submitted output or None, the agent's visible text, usage)."""
    submit = ROLES[role]["submit"]
    usage = new_usage()
    tools = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
             for t in mcp_tools] + [submit]
    mcp_names = {t.name for t in mcp_tools}
    log.record("agent_start", step=step, role=role, tools=[t["name"] for t in tools], message=user_msg)

    if dry_run:
        return await dry_run_agent(role, session, log, step, user_msg), "(dry run)", usage

    import anthropic
    messages: list = [{"role": "user", "content": user_msg}]
    texts: list[str] = []
    calls, reminded = 0, False
    while True:
        t0 = time.perf_counter()
        try:
            # Two cache breakpoints: the system prompt (marked in system_prompt()), and the
            # top-level automatic one, which moves to the end of the conversation on every call,
            # so each turn of the tool loop re-reads everything before it from the cache.
            resp = await client.beta.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS, system=system_prompt(role), tools=tools,
                messages=messages, betas=[FALLBACK_BETA], fallbacks="default",
                cache_control={"type": "ephemeral"})
        except anthropic.RateLimitError:
            log.record("agent_error", step=step, role=role, error="rate limited")
            return None, "\n".join(texts), usage
        except anthropic.APIStatusError as e:
            log.record("agent_error", step=step, role=role, error=f"API {e.status_code}: {e.message}")
            return None, "\n".join(texts), usage
        except anthropic.APIConnectionError:
            log.record("agent_error", step=step, role=role, error="network error")
            return None, "\n".join(texts), usage
        finally:
            usage["seconds"] += time.perf_counter() - t0     # time waiting on Claude (runs/log.jsonl)

        u = resp.usage
        part = {"calls": 1, "in": u.input_tokens or 0, "out": u.output_tokens or 0,
                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0}
        add_usage(usage, part)
        for b in resp.content:
            if b.type == "text" and b.text.strip():
                texts.append(b.text.strip())
        log.record("model_response", step=step, role=role, stop_reason=resp.stop_reason,
                   model=resp.model, usage=part,
                   text=[b.text for b in resp.content if b.type == "text"])

        if resp.stop_reason == "refusal":
            log.record("agent_error", step=step, role=role, error="refusal")
            return None, "\n".join(texts), usage
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            if not reminded and resp.stop_reason == "end_turn":
                reminded = True
                messages += [{"role": "assistant", "content": resp.content},
                             {"role": "user", "content": f"Please finish by calling {submit['name']} exactly once."}]
                continue
            log.record("agent_error", step=step, role=role,
                       error=f"stopped ({resp.stop_reason}) without calling {submit['name']}")
            return None, "\n".join(texts), usage

        messages.append({"role": "assistant", "content": resp.content})
        results, submitted = [], None
        for tu in tool_uses:
            calls += 1
            if tu.name == submit["name"]:
                submitted = tu.input
                text, err = "Received. Thank you.", False
            elif tu.name in mcp_names and calls <= MAX_TOOL_CALLS:
                try:
                    r = await session.call_tool(tu.name, tu.input)
                    text = "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")
                    err = bool(r.is_error)
                except Exception as exc:
                    text, err = f"Tool failed: {exc}", True
            elif calls > MAX_TOOL_CALLS:
                text, err = (f"Tool-call limit ({MAX_TOOL_CALLS}) reached. Call {submit['name']} now "
                             "with what you have."), True
            else:
                text, err = f"Unknown tool: {tu.name}", True
            log.record("tool_call", step=step, role=role, tool=tu.name, input=tu.input,
                       is_error=err, result=text)
            print(f"      {role:<8} {tu.name}({preview(json.dumps(tu.input), 70)})"
                  + (" ERROR" if err else ""))
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": text, "is_error": err})
        if submitted is not None:
            log.record("agent_submit", step=step, role=role, output=submitted, usage=usage)
            return submitted, "\n".join(texts), usage
        if calls > MAX_TOOL_CALLS + 3:
            log.record("agent_error", step=step, role=role, error="tool-call limit; no submission")
            return None, "\n".join(texts), usage
        messages.append({"role": "user", "content": results})


async def dry_run_agent(role: str, session: ClientSession, log: RunLog, step: int, msg: str) -> dict:
    """No API call: exercise the real MCP tools, then return a canned, clearly-labeled answer."""
    clock = json.loads((log.dir / "clock.json").read_text(encoding="utf-8"))
    probes = [("get_sensor_readings", {"event_id": clock["event_id"], "up_to_time": clock["now"]}),
              ("get_health_status", {"time": clock["now"]}),
              ("search_rules", {"query": "ROE-4.1"})]
    if role == "safety":
        probes.append(("get_control_room_info", {"event_id": clock["event_id"], "time": clock["now"]}))
        probes.append(("get_health_status", {"time": "2026-12-31 00:00:00"}))   # must be refused
    for name, args in probes:
        r = await session.call_tool(name, args)
        text = "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")
        log.record("tool_call", step=step, role=role, tool=name, input=args, is_error=bool(r.is_error),
                   result=text[:2000])
        print(f"      {role:<8} {name}  -> {'ERROR: ' + preview(text, 80) if r.is_error else f'{len(text):,} chars'}")
    final = step == STEPS_PER_EVENT
    if role == "analyst":
        out = {"tracks": [], "threat_level": "MEDIUM" if final else "LOW", "indicators_up": [],
               "indicators_down": [], "recommended_rung": 3 if final else 2,
               "recommended_action": "DRY RUN: RF jammer" if final else "DRY RUN: send security",
               "options": [], "notifications": [], "confidence": "LOW",
               "what_would_change": "dry run", "citations": []}
    elif role == "reviewer":
        reject = step in DRY_REJECT_STEPS
        out = {"own_assessment": "dry run", "verdict": "REJECT" if reject else "APPROVE", "discrepancies": [],
               "reasons": "DRY RUN: reviewer told to reject (--dry-reject)" if reject else "dry run",
               "would_accept": "", "notes": "", "citations": []}
    else:
        out = {"advice": "CONCUR", "new_information": [], "pvid_status": "not applicable",
               "override_assessment": "no override", "concerns": "dry run",
               "safer_alternative": "", "citations": []}
    log.record("agent_submit", step=step, role=role, output=out, usage=new_usage(), dry_run=True)
    return out


# ---------------------------------------------------------------------------
# Humans: operator and control room
# ---------------------------------------------------------------------------
class WebHandoff:
    """--web: the pipeline and the Streamlit page talk through two small files in the run folder.

    1. Pipeline writes  pending.json  {id, role, step, now, posted, choices, ...context}
    2. The page shows buttons; a click writes  answer.json  {id, decision, reason, override_action?}
    3. Pipeline checks the answer (right id, allowed decision, reason where required), logs it,
       and deletes both files. A bad answer is logged and ignored; the pipeline keeps waiting.
    Operator and control room: no time limit; the pipeline waits for a person to decide.
    Nothing is carried out until the control room approves (ROE-1.6).
    Both files are written via a temp file + os.replace so neither side reads half a file.
    While waiting, the pipeline touches pending.json every poll (heartbeat); the page treats a
    pending.json untouched for 15 s as dead (pipeline killed) and shows no buttons for it.
    """
    POLL_SECONDS = 0.5

    def __init__(self, run_dir: Path, log: "RunLog"):
        self.pending = run_dir / "pending.json"
        self.answer = run_dir / "answer.json"
        self.log = log

    @staticmethod
    def write_atomic(path: Path, data: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)

    def check(self, req: dict, ans: dict) -> str | None:
        """Return why an answer is not acceptable, or None if it is."""
        if ans.get("id") != req["id"]:
            return f"answer id {ans.get('id')!r} does not match {req['id']!r}"
        d = ans.get("decision")
        if d not in req["choices"]:
            return f"decision {d!r} is not one of {req['choices']}"
        reason = str(ans.get("reason") or "").strip()
        if d in ("override", "stop") and not reason:
            return f"{d} needs a written reason"
        if d == "override" and not req["do_not_engage"] and "override_action" in ans:
            oa = ans["override_action"]
            if not (isinstance(oa, dict) and isinstance(oa.get("rung"), int) and 3 <= oa["rung"] <= 6
                    and str(oa.get("action") or "").strip()):
                return "override_action needs a rung 3-6 and an action"
        return None

    async def ask(self, role: str, step: int, context: dict, choices: list[str]) -> dict:
        loop = asyncio.get_running_loop()
        start = loop.time()
        posted = dt.datetime.now()
        req = {"id": f"step{step}-{role}-{posted.strftime('%H%M%S%f')}", "role": role, "step": step,
               "posted": posted.isoformat(timespec="seconds"), "choices": choices, "do_not_engage": context.get("do_not_engage", False), **context}
        self.answer.unlink(missing_ok=True)                 # never pick up a stale answer
        self.write_atomic(self.pending, req)
        self.log.record("web_request", step=step, role=role, request_id=req["id"])
        print(f"      waiting for the {role.replace('_', ' ')} on the web page (no time limit) ...")
        try:
            while True:
                if self.answer.exists():
                    try:
                        ans = json.loads(self.answer.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as e:
                        ans, problem = {}, f"unreadable answer file: {e}"
                    else:
                        problem = self.check(req, ans)
                    self.answer.unlink(missing_ok=True)
                    if problem is None:
                        out = {"decision": ans["decision"], "reason": str(ans.get("reason") or "").strip(),
                               "source": "web",
                               "seconds_to_decide": round(loop.time() - start, 1)}
                        if ans["decision"] == "override" and "override_action" in ans and not req["do_not_engage"]:
                            out["override_action"] = ans["override_action"]
                        return out
                    self.log.record("web_answer_rejected", step=step, role=role, problem=problem)
                    print(f"      answer ignored: {problem}")
                await asyncio.sleep(self.POLL_SECONDS)
                try:
                    os.utime(self.pending)                  # heartbeat: the page ignores stale requests
                except OSError:
                    pass
        finally:
            self.pending.unlink(missing_ok=True)


class Humans:
    def __init__(self, mode: str, event_id: str, web: WebHandoff | None = None):
        self.mode = mode                                    # "simulated" | "interactive" | "web"
        self.interactive = mode == "interactive"
        self.web = web
        data = json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
        self.defaults = data["defaults"]
        self.script = data.get("events", {}).get(event_id, {})

    def _ask(self, prompt: str, choices: list[str]) -> str:
        while True:
            a = input(f"{prompt} [{'/'.join(choices)}]: ").strip().lower()
            if a in choices:
                return a

    async def operator(self, step: int, shown: dict, now: str) -> dict:
        if self.mode == "web":
            return await self.web.ask("operator", step, {"now": now, "shown": shown},
                                      ["accept", "reject", "override"])
        if self.interactive:
            choices = ["accept", "reject", "override"]
            d = self._ask("OPERATOR decision", choices)
            reason = input("  Reason (required for override): ").strip() if d != "accept" else ""
            while d == "override" and not reason:
                reason = input("  An override needs a written reason: ").strip()
            out = {"decision": d, "reason": reason, "source": "interactive"}
            if d == "override" and not shown["do_not_engage"]:
                rung = int(input("  Requested rung (3-6): ").strip() or "3")
                out["override_action"] = {"rung": rung, "action": input("  Requested action: ").strip()}
            return out
        s = self.script.get(str(step), {})
        out = {"decision": s.get("operator", self.defaults["operator"]),
               "reason": s.get("operator_reason", ""), "source": "SIMULATED (decisions.json)"}
        if "override_action" in s:
            out["override_action"] = s["override_action"]
        return out

    async def control_room(self, step: int, advice: dict | None, request: dict | None = None) -> dict:
        if self.mode == "web":
            return await self.web.ask("control_room", step, {**(request or {}), "advice": advice},
                                      ["approve", "stop"])
        if self.interactive:
            d = self._ask("CONTROL ROOM decision", ["approve", "stop", "no_response"])
            reason = input("  Reason: ").strip() if d == "stop" else ""
            return {"decision": d, "reason": reason, "source": "interactive"}
        s = self.script.get(str(step), {})
        d = s.get("control_room", self.defaults["control_room"])
        reason = s.get("control_room_reason", "")
        if d == "follow_safety_advice":
            if advice is None:
                d, reason = "no_response", "No safety advice available; simulated control room did not respond."
            elif advice.get("advice") == "RECOMMEND STOP":
                d, reason = "stop", "Following safety agent: RECOMMEND STOP."
            else:
                d, reason = "approve", f"Following safety agent: {advice.get('advice')}."
        return {"decision": d, "reason": reason, "source": "SIMULATED (decisions.json)"}


# ---------------------------------------------------------------------------
# One step of the pipeline
# ---------------------------------------------------------------------------
def summarize_assessment(a: dict) -> str:
    blocked = [f"{o['option']}: {o['reasons']}" for o in a.get("options", []) if o.get("status") == "BLOCKED"]
    return (f"threat {a.get('threat_level')}, rung {a.get('recommended_rung')}: {a.get('recommended_action')}"
            + (f"\n        blocked: " + "\n                 ".join(preview(b, 110) for b in blocked) if blocked else ""))


async def run_step(event_id: str, step: int, now: str, ctx: dict) -> dict:
    log: RunLog = ctx["log"]
    (log.dir / "clock.json").write_text(json.dumps({"event_id": event_id, "now": now}), encoding="utf-8")
    log.say(f"\n## Step {step} of {STEPS_PER_EVENT} - {now}")
    log.record("step_start", step=step, now=now)
    usage = new_usage()
    prev = ctx.get("previous")

    # 1. Analyst
    msg = (f"Event {event_id}. Current time: {now} (step {step} of {STEPS_PER_EVENT}; readings arrive "
           f"every {STEP_SECONDS} s). Assess the situation now and recommend a response."
           + (f"\n\nYour assessment at the previous step was: {jdump(prev)}" if prev else ""))
    a, a_text, u = await run_agent("analyst", *ctx["agents"]["analyst"], ctx["client"], msg, log, step, ctx["dry"])
    add_usage(usage, u)
    if a is None:
        log.say("- **Analyst:** FAILED (no assessment). Nothing goes to the operator; tracking continues.")
        return {"usage": usage, "outcome": "analyst failed", "final_rung": 1}
    ctx["previous"] = {k: a.get(k) for k in ("threat_level", "recommended_rung", "recommended_action")}
    log.say(f"- **Analyst:** {summarize_assessment(a)}")

    # 2. Reviewer
    msg = (f"Event {event_id}. Current time: {now}. Review the analyst's proposal below.\n\n"
           f"<analyst_proposal>\n{jdump(a)}\n</analyst_proposal>\n\n"
           f"<analyst_reasoning>\n{a_text or '(none written)'}\n</analyst_reasoning>")
    r, _, u = await run_agent("reviewer", *ctx["agents"]["reviewer"], ctx["client"], msg, log, step, ctx["dry"])
    add_usage(usage, u)
    if r is None:
        r = {"verdict": "REJECT", "reasons": "Reviewer failed to respond; treated as REJECT (fail safe)."}
    dne = r["verdict"] == "REJECT"
    shown = {"do_not_engage": dne,
             "recommended_rung": min(a["recommended_rung"], 2) if dne else a["recommended_rung"],
             "recommended_action": "DO NOT ENGAGE" if dne else a["recommended_action"],
             "reviewer_reasons": r.get("reasons", ""), "analyst_proposal": a["recommended_action"]}
    log.say(f"- **Reviewer:** {r['verdict']} - {preview(r.get('reasons', ''), 200)}")
    log.say(f"- **Shown to operator:** {shown['recommended_action']}")
    log.record("shown_to_operator", step=step, shown=shown)

    # 3. Operator
    op = await ctx["humans"].operator(step, shown, now)
    requested_rung, requested_action = 0, "none (automatic tracking only)"
    if op["decision"] == "accept":
        requested_rung, requested_action = shown["recommended_rung"], shown["recommended_action"]
        if dne:
            requested_rung, requested_action = 1, "DO NOT ENGAGE accepted (tracking continues)"
    elif op["decision"] == "override":
        if dne:
            requested_rung, requested_action = a["recommended_rung"], a["recommended_action"]
        elif "override_action" in op:
            requested_rung = op["override_action"]["rung"]
            requested_action = op["override_action"]["action"]
        else:
            requested_rung, requested_action = shown["recommended_rung"], shown["recommended_action"]
    overrode = op["decision"] == "override"
    log.say(f"- **Operator** ({op['source']}): {op['decision'].upper()}"
            + (f" - reason: {op['reason']}" if op.get("reason") else "")
            + f" -> requests rung {requested_rung}: {requested_action}")
    log.record("operator_decision", step=step, decision=op, requested_rung=requested_rung,
               requested_action=requested_action)

    # 4-5. Safety agent and control room, only when the control room must decide
    advice, cr = None, None
    if requested_rung >= CONTROL_ROOM_RUNG or overrode:
        flag = "OPERATOR OVERRODE REVIEWER. " if overrode and dne else (
               "OPERATOR REQUESTED A STRONGER ACTION THAN RECOMMENDED. " if overrode else "")
        msg = (f"Event {event_id}. Current time: {now}. {flag}Advise the control room on this request.\n\n"
               f"<analyst_proposal>\n{jdump(a)}\n</analyst_proposal>\n\n"
               f"<reviewer_verdict>\n{jdump(r)}\n</reviewer_verdict>\n\n"
               f"<operator_request>\nDecision: {op['decision']}\nRequested rung: {requested_rung}\n"
               f"Requested action: {requested_action}\nOperator's reason: {op.get('reason') or '(none)'}\n"
               f"</operator_request>")
        advice, _, u = await run_agent("safety", *ctx["agents"]["safety"], ctx["client"], msg, log, step, ctx["dry"])
        add_usage(usage, u)
        if advice is None:
            log.say("- **Safety agent:** NO SAFETY ADVICE AVAILABLE (request passes through; ROE-4.5)")
        else:
            log.say(f"- **Safety agent:** {advice['advice']} - {preview(advice.get('concerns', ''), 200)}")
            for n in advice.get("new_information", []):
                log.say(f"    - new info {n.get('control_room_id')}: {preview(n.get('info', ''), 150)}")
        cr = await ctx["humans"].control_room(step, advice, {
            "now": now, "shown": shown, "operator": op, "overrode_reviewer": overrode and dne,
            "requested_rung": requested_rung, "requested_action": requested_action,
            "reviewer_verdict": r["verdict"], "reviewer_reasons": r.get("reasons", "")})
        log.say(f"- **Control room** ({cr['source']}): {cr['decision'].upper()}"
                + (f" - {cr['reason']}" if cr.get("reason") else ""))
        log.record("control_room_decision", step=step, decision=cr)
        approved = cr["decision"] == "approve"
        outcome = (f"APPROVED: rung {requested_rung} - {requested_action}" if approved else
                   f"NOT APPROVED ({cr['decision']}): rung {requested_rung} request not carried out")
        final_rung = requested_rung if approved else 2 if cr["decision"] == "stop" else 1
    else:
        outcome = f"Operator authority: rung {requested_rung} - {requested_action}"
        final_rung = requested_rung

    log.say(f"- **Outcome:** {outcome}")
    log.say(f"- Tokens this step: {usage['in']:,} in + {usage['cache_read']:,} cache read + "
            f"{usage['cache_write']:,} cache write, {usage['out']:,} out = ${cost_of(usage):.4f}")
    log.record("step_end", step=step, outcome=outcome, final_rung=final_rung, usage=usage,
               cost_usd=round(cost_of(usage), 5))
    return {"usage": usage, "outcome": outcome, "final_rung": final_rung,
            "analyst": a, "reviewer_verdict": r["verdict"], "shown": shown["recommended_action"],
            "operator": op["decision"], "advice": advice and advice.get("advice"),
            "control_room": cr and cr["decision"]}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main_async(args) -> None:
    event_id = args.event.zfill(2)
    times = event_steps(event_id)
    steps = choose_steps(args.steps, len(times))
    log = RunLog(event_id, args.dry_run)
    pv = prompt_version()
    client = None
    if not args.dry_run:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=load_api_key())

    log.say(f"# Fort GBUS run {log.run_id}")
    log.say(f"- Event {event_id}; steps {steps} of {len(times)}; model {MODEL}"
            + ("; **DRY RUN (no API calls)**" if args.dry_run else "")
            + (f"; dry-run reviewer REJECTs at steps {sorted(DRY_REJECT_STEPS)}" if DRY_REJECT_STEPS else ""))
    mode = "web" if args.web else "interactive" if args.interactive else "simulated"
    log.say(f"- Prompts {pv['version']} (hash {pv['hash']}); human decisions: "
            + {"web": "web page (no time limits; the people decide)",
               "interactive": "interactive",
               "simulated": "SIMULATED from decisions.json"}[mode])
    log.record("run_start", run_id=log.run_id, event=event_id, steps=steps, model=MODEL,
               prompts=pv, dry_run=args.dry_run, interactive=args.interactive, humans=mode,
               dry_reject=sorted(DRY_REJECT_STEPS))

    clock_path = log.dir / "clock.json"
    clock_path.write_text(json.dumps({"event_id": event_id, "now": times[0]}), encoding="utf-8")
    web = WebHandoff(log.dir, log) if args.web else None
    ctx = {"log": log, "client": client, "dry": args.dry_run,
           "humans": Humans(mode, event_id, web), "agents": {}}
    total = new_usage()
    results = []
    server_log = open(log.dir / "mcp-servers.log", "w", encoding="utf-8")
    try:
        async with AsyncExitStack() as stack:
            for role, cfg in ROLES.items():
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[str(SERVER), "--role", cfg["server_role"], "--clock", str(clock_path)],
                    cwd=str(HERE))
                read, write = await stack.enter_async_context(stdio_client(params, errlog=server_log))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools = (await session.list_tools()).tools
                ctx["agents"][role] = (session, tools)
                log.record("mcp_server", role=role, tools=[t.name for t in tools])
            log.say("- MCP tools: " + "; ".join(f"{r}={len(t)}" for r, (_, t) in ctx["agents"].items()))

            for step in steps:
                res = await run_step(event_id, step, times[step - 1], ctx)
                add_usage(total, res["usage"])
                results.append((step, res))
    finally:
        server_log.close()
        last = results[-1][1] if results else {}
        cost = cost_of(total)
        log.say("\n## Run totals")
        log.say(f"- Model calls: {total['calls']}; tokens: {total['in']:,} in, {total['cache_read']:,} "
                f"cache read, {total['cache_write']:,} cache write, {total['out']:,} out")
        log.say(f"- Estimated cost: ${cost:.4f}")
        log.say(f"- Final outcome: {last.get('outcome', 'none')}")
        log.record("run_end", usage=total, cost_usd=round(cost, 5), final=last.get("outcome"))
        log.close()
        write_index(log, event_id, steps, pv, total, cost, last, args)
        if not args.dry_run:
            write_course_log(event_id, steps, total, results)
        print(f"\nLog: {log.dir}")


def steps_label(steps: list[int]) -> str:
    """[1..7] -> '1-7'; [7] -> '7'; [1, 4, 7] -> '1,4,7'. Same steps always give the same label."""
    if len(steps) > 1 and steps == list(range(steps[0], steps[-1] + 1)):
        return f"{steps[0]}-{steps[-1]}"
    return ",".join(map(str, steps))


def run_output(steps: list[int], results: list) -> str:
    """The run's final outcome in one line, from the last step that finished."""
    if not results:
        return f"INCOMPLETE: no step finished (0 of {len(steps)})."
    step, last = results[-1]
    parts = [f"Step {step}: {last.get('outcome', 'no outcome')}."]
    if "shown" in last:
        parts.append(f"Shown to operator: {last['shown']}.")
        parts.append(f"Operator: {str(last.get('operator', '')).upper()}.")
        parts.append(f"Control room: {str(last['control_room']).upper()}." if last.get("control_room")
                     else "Control room: not needed.")
    text = " ".join(parts)
    if len(results) < len(steps):
        text = f"INCOMPLETE ({len(results)} of {len(steps)} steps finished). " + text
    return text


def write_course_log(event_id: str, steps: list[int], total: dict, results: list) -> None:
    """Append ONE line to runs/log.jsonl (the course run log). Real runs only; exactly 7 fields."""
    row = {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
           "model": MODEL,
           "input": f"event {event_id}, steps {steps_label(steps)}",
           "output": run_output(steps, results),
           "input_tokens": total["in"] + total["cache_read"] + total["cache_write"],
           "output_tokens": total["out"],
           "seconds": round(total["seconds"], 1)}
    with open(RUNS / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_index(log, event_id, steps, pv, total, cost, last, args) -> None:
    path = RUNS / "run-index.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["run_id", "event", "steps", "dry_run", "prompts", "model", "model_calls",
                        "input_tokens", "cache_read", "cache_write", "output_tokens", "cost_usd",
                        "final_rung", "final_outcome", "code_grade", "human_grade", "human_notes"])
        w.writerow([log.run_id, event_id, " ".join(map(str, steps)), args.dry_run,
                    f"{pv['version']}/{pv['hash']}", MODEL, total["calls"], total["in"],
                    total["cache_read"], total["cache_write"], total["out"], f"{cost:.4f}",
                    last.get("final_rung", ""), last.get("outcome", ""), "", "", ""])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Run the Fort GBUS counter-drone pipeline for one event.")
    ap.add_argument("--event", required=True, help="event ID, 01-10")
    ap.add_argument("--steps", default="all", help="'all' (default), 'last', or e.g. '1,4,7'")
    ap.add_argument("--dry-run", action="store_true", help="no API calls: test the plumbing only")
    who = ap.add_mutually_exclusive_group()
    who.add_argument("--interactive", action="store_true", help="you type the operator and control-room decisions")
    who.add_argument("--web", action="store_true",
                     help="you make the decisions with buttons on the Streamlit page (runs/<id>/pending.json)")
    ap.add_argument("--dry-reject", default="", metavar="STEPS",
                    help="dry run only: the canned reviewer REJECTs at these steps, e.g. '7' or '3,7' "
                         "(to test DO NOT ENGAGE and the override button for free)")
    args = ap.parse_args()
    if args.dry_reject:
        if not args.dry_run:
            sys.exit("--dry-reject only works with --dry-run.")
        try:
            DRY_REJECT_STEPS.update(int(s) for s in args.dry_reject.split(","))
        except ValueError:
            sys.exit("--dry-reject must be step numbers like 7 or 3,7")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
