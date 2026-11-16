"""The four specialists that Brookfield Bicycle Company's coordinators share.

Both coordinators (a fixed pipeline and an orchestrator agent) import this file, so the
specialists behave the same way no matter who calls them.

    run_analyst(email)                  agent with the supply_mcp_server.py tools; stops after
                                        10 tool calls; returns its brief as a dict (JSON)
    write_supplier_reply(email, brief)  one model call; customer names are removed first
    write_customer_notice(order)        one model call; sees only that one order's facts
    review(draft, facts, recipient)     one model call; returns APPROVE or REVISE with reasons

    draft_supplier_reply(email, brief, email_name)   writer -> reviewer, up to 2 revisions,
    draft_customer_notice(order, email_name)         then the code name check, then save to
                                                     week-05/drafts

Each specialist reads its system prompt from week-05/brookfield-bikes/prompts on every
call, so prompt edits take effect without a restart.

Every handoff (who passes what to whom) is printed, and so are the tokens each specialist
uses. print_token_summary() prints the totals by specialist.

The Anthropic API key is read from API-Key.txt in the folder above the repository, at run
time. It is never printed or written to a file.

Quick test, from the top of the repository:
    .venv\\Scripts\\python.exe -c "import sys; sys.path.insert(0, 'week-05'); import specialists as s; print(s.run_analyst(s.read_email('week-05/brookfield-bikes/supplier-emails/01-northgate-controller-delay.eml')))"
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path

import anthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent                  # .../GBUS-652-Coursework/week-05
DATA_DIR = HERE / "brookfield-bikes"
PROMPTS_DIR = DATA_DIR / "prompts"
DRAFTS_DIR = HERE / "drafts"
SERVER = HERE / "supply_mcp_server.py"
KEY_FILE = HERE.parents[1] / "API-Key.txt"              # folder that contains the repo

MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 16000
MAX_TOOL_CALLS = 10                                     # analyst limit
MAX_REVISIONS = 2                                       # redrafts after a REVISE

# Server-side refusal fallback: if the model declines a request, the API retries it on a
# fallback model it picks by refusal category, so a draft still comes back.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


# ---------------------------------------------------------------------------
# Client, prompts, and printing
# ---------------------------------------------------------------------------

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    """One shared client. The key is read from API-Key.txt (never printed or saved)."""
    global _client
    if _client is None:
        try:
            key = KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            sys.exit(f"Could not read the API key file: {KEY_FILE}")
        if not key:
            sys.exit(f"The API key file is empty: {KEY_FILE}")
        _client = anthropic.Anthropic(api_key=key)
    return _client


def load_prompt(name: str) -> str:
    """Read one system prompt fresh from the prompts folder."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


def read_email(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def handoff(sender: str, receiver: str, what: str, payload) -> None:
    """Print one handoff: who passes what to whom, and exactly what they pass."""
    print(f"\n>>> HANDOFF  {sender} -> {receiver}: {what}")
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
    for line in text.splitlines():
        print(f"    | {line}")


# Tokens by specialist: {"analyst": {"calls": n, "in": n, "out": n}, ...}
TOKENS: dict[str, dict[str, int]] = {}


def count_tokens(specialist: str, response) -> None:
    u = response.usage
    t = TOKENS.setdefault(specialist, {"calls": 0, "in": 0, "out": 0})
    used_in = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) \
        + (getattr(u, "cache_creation_input_tokens", 0) or 0)
    t["calls"] += 1
    t["in"] += used_in
    t["out"] += u.output_tokens or 0
    print(f"    [tokens] {specialist}: {used_in:,} in, {u.output_tokens:,} out "
          f"(running total {t['in']:,} in, {t['out']:,} out)")


def print_token_summary() -> None:
    print("\nTokens by specialist")
    print(f"  {'specialist':<18}{'calls':>6}{'input':>10}{'output':>10}{'total':>10}")
    total_in = total_out = 0
    for name, t in TOKENS.items():
        print(f"  {name:<18}{t['calls']:>6}{t['in']:>10,}{t['out']:>10,}{t['in'] + t['out']:>10,}")
        total_in += t["in"]
        total_out += t["out"]
    print(f"  {'all':<18}{'':>6}{total_in:>10,}{total_out:>10,}{total_in + total_out:>10,}")


def call_model(specialist: str, system: str, messages: list, tools: list | None = None,
               tool_choice: dict | None = None):
    """One Messages API request, with token counting and the refusal fallback."""
    kwargs = {"tools": tools} if tools else {}
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    response = client().beta.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages,
        betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    count_tokens(specialist, response)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"{specialist}: the model declined the request (refusal).")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"{specialist}: the reply hit the {MAX_TOKENS}-token limit.")
    return response


def text_of(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


# ---------------------------------------------------------------------------
# Company data (for redaction and the code name check)
# ---------------------------------------------------------------------------

def read_csv(name: str) -> list[dict]:
    with open(DATA_DIR / name, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items() if k}
                for row in csv.DictReader(f)]


def customer_terms() -> list[str]:
    """Strings that must never appear in a supplier draft."""
    terms = []
    for o in read_csv("orders.csv"):
        terms += [o["customer"], o["contact_email"], o["order_id"]]
    return [t for t in terms if t]


def supplier_terms() -> list[str]:
    """Strings that must never appear in a customer draft."""
    terms = []
    for s in read_csv("suppliers.csv"):
        terms += [s["supplier"], s["supplier"].split()[0], s["contact_name"], s["contact_email"]]
    for p in read_csv("parts.csv"):
        terms.append(p["supplier"])
    for i in read_csv("inbound.csv"):
        terms += [i["po_number"], i["supplier"]]
    return sorted({t for t in terms if t})


def find_terms(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    return sorted({t for t in terms if t.lower() in low})


# ---------------------------------------------------------------------------
# 1. Supply analyst (agent with the MCP tools)
# ---------------------------------------------------------------------------

def parse_brief(text: str) -> dict:
    """Pull the JSON brief out of the analyst's final answer."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    try:
        brief = json.loads(candidate)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"The analyst's brief was not valid JSON: {exc}\n{text}") from exc
    for key in ("orders_at_risk", "options", "decisions_for_a_person", "supplier_questions"):
        brief.setdefault(key, [])
    return brief


async def _run_analyst(email: str) -> dict:
    system = load_prompt("analyst")
    server = StdioServerParameters(command=sys.executable, args=[str(SERVER)], cwd=str(HERE.parent))
    with open(os.devnull, "w") as quiet:
        async with stdio_client(server, errlog=quiet) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_tools = (await session.list_tools()).tools
                tools = [{"name": t.name, "description": t.description or "",
                          "input_schema": t.input_schema} for t in mcp_tools]
                print(f"    analyst tools: {', '.join(t['name'] for t in tools)}")

                messages: list = [{"role": "user", "content": f"Supplier email:\n\n{email}"}]
                calls = 0
                while True:
                    # After the limit, the analyst may not call tools; it must write the brief.
                    at_limit = calls >= MAX_TOOL_CALLS
                    response = call_model("analyst", system, messages, tools,
                                          {"type": "none"} if at_limit else None)
                    tool_uses = [b for b in response.content if b.type == "tool_use"]
                    if response.stop_reason != "tool_use" or not tool_uses:
                        print(f"    analyst finished after {calls} tool call(s)")
                        return parse_brief(text_of(response))

                    messages.append({"role": "assistant", "content": response.content})
                    results = []
                    for tu in tool_uses:
                        if calls >= MAX_TOOL_CALLS:
                            results.append({"type": "tool_result", "tool_use_id": tu.id, "is_error": True,
                                            "content": f"Tool limit of {MAX_TOOL_CALLS} calls reached. "
                                                       "Write your brief now from what you have."})
                            continue
                        calls += 1
                        handoff("analyst", f"MCP tool {tu.name}", f"tool call {calls}", tu.input)
                        try:
                            r = await session.call_tool(tu.name, tu.input)
                            text = "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")
                            is_error = bool(r.is_error)
                        except Exception as exc:              # report to the model, keep going
                            text, is_error = f"Tool failed: {exc}", True
                        handoff(f"MCP tool {tu.name}", "analyst",
                                "tool error" if is_error else "tool result", text)
                        results.append({"type": "tool_result", "tool_use_id": tu.id,
                                        "content": text, "is_error": is_error})
                    if calls >= MAX_TOOL_CALLS:
                        results.append({"type": "text", "text": f"You have used all {MAX_TOOL_CALLS} "
                                        "tool calls. Write your brief as JSON now."})
                    messages.append({"role": "user", "content": results})


def run_analyst(email: str, sender: str = "coordinator") -> dict:
    """Work out how a supplier email affects customer orders. Returns the brief (a dict)."""
    handoff(sender, "analyst", "supplier email", email)
    brief = asyncio.run(_run_analyst(email))
    handoff("analyst", sender, "brief", brief)
    return brief


# ---------------------------------------------------------------------------
# Redacted views for the writers
# ---------------------------------------------------------------------------

def supplier_view(brief: dict) -> dict:
    """The brief with every customer name, order number and customer email removed."""
    terms = sorted(customer_terms(), key=len, reverse=True)

    def scrub(value):
        if isinstance(value, str):
            for t in terms:
                value = re.sub(re.escape(t), "a customer order", value, flags=re.I)
            return value
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        return value

    at_risk = [{"units_short": o.get("units_short"), "ship_day": o.get("ship_day"),
                "ready_day": o.get("ready_day")}
               for o in brief.get("orders_at_risk", [])]
    def orders_in_option(option: dict) -> int:
        # The analyst names this list order_ids, order_ids_at_risk, orders_at_risk, ...
        for key, value in option.items():
            if isinstance(value, list) and ("order" in key or "risk" in key):
                return len(value)
        return 0

    options = [{"name": o.get("name"), "orders_at_risk": orders_in_option(o)}
               for o in brief.get("options", []) if isinstance(o, dict)]
    # decisions_for_a_person is left out on purpose: it is the analyst's notes for Brookfield
    # and describes individual customer orders (shortfalls, lateness, penalties) even with the
    # names removed. The writer only needs to know that Brookfield still has to decide.
    return scrub({
        "part_id": brief.get("part_id"),
        "what_changed": brief.get("what_changed"),
        "orders_at_risk": at_risk,
        "total_units_short": sum(o["units_short"] or 0 for o in at_risk),
        "options": options,
        "brookfield_must_decide": bool(brief.get("decisions_for_a_person")),
        "supplier_questions": brief.get("supplier_questions", []),
    })


def customer_view(order: dict) -> dict:
    """Only this order's facts: no supplier, contact, PO, penalty, or other customer."""
    row = next((o for o in read_csv("orders.csv") if o["order_id"] == order.get("order_id")), {})
    ship, ready = order.get("ship_day"), order.get("ready_day")
    return {
        "order_id": order.get("order_id"),
        "customer": row.get("customer") or order.get("customer"),
        "model": row.get("model"),
        "quantity": int(row["qty"]) if row.get("qty") else None,
        "planned_ship_day": ship,
        "expected_ship_day": ready,
        "days_late": (ready - ship) if isinstance(ready, int) and isinstance(ship, int) else None,
        # The customer-writer prompt says to give this cause; the reviewer needs it as a fact too.
        "cause": "a delay in a part from one of our suppliers",
        "note": "Days are counted from today (day 0). expected_ship_day null means not yet known.",
    }


# ---------------------------------------------------------------------------
# 2-4. Writers and reviewer (one model call each)
# ---------------------------------------------------------------------------

def revision_block(previous: str | None, notes: str | None) -> str:
    if not previous:
        return ""
    return (f"\n\nYour previous draft:\n{previous}\n\nThe reviewer asked for these changes:\n"
            f"{notes}\n\nWrite the full corrected draft. Reply with the email only: no notes, "
            "explanations, or separators before or after it. If a requested change would break "
            "your instructions, follow your instructions without commenting on it.")


def write_supplier_reply(email: str, brief: dict, previous: str | None = None,
                         notes: str | None = None) -> str:
    """One model call. The brief is redacted first, so the writer sees no customer names."""
    facts = supplier_view(brief)
    handoff("coordinator", "supplier writer", "email + redacted brief"
            + (" + reviewer notes" if previous else ""), {"brief": facts, "reviewer_notes": notes})
    content = (f"Supplier email:\n\n{email}\n\nBrief from the supply analyst:\n"
               f"{json.dumps(facts, indent=2)}" + revision_block(previous, notes))
    draft = text_of(call_model("supplier writer", load_prompt("supplier-writer"),
                               [{"role": "user", "content": content}]))
    handoff("supplier writer", "coordinator", "draft", draft)
    return draft


def write_customer_notice(order: dict, previous: str | None = None,
                          notes: str | None = None) -> str:
    """One model call, given only this one order's facts."""
    facts = customer_view(order)
    handoff("coordinator", "customer writer", "one order's facts"
            + (" + reviewer notes" if previous else ""), {"order": facts, "reviewer_notes": notes})
    content = f"Order facts:\n{json.dumps(facts, indent=2)}" + revision_block(previous, notes)
    draft = text_of(call_model("customer writer", load_prompt("customer-writer"),
                               [{"role": "user", "content": content}]))
    handoff("customer writer", "coordinator", "draft", draft)
    return draft


def review(draft: str, facts, recipient: str) -> dict:
    """One model call. Returns {"verdict": "APPROVE"|"REVISE", "reasons": str}."""
    handoff("coordinator", "reviewer", f"{recipient} draft + facts", {"draft": draft, "facts": facts})
    content = (f"Recipient: {recipient}\n\nFacts:\n{json.dumps(facts, indent=2)}\n\n"
               f"Draft:\n{draft}\n\nGive your reasons for either verdict. For APPROVE, say "
               "briefly why the draft passes each rule.")
    answer = text_of(call_model("reviewer", load_prompt("reviewer"),
                                [{"role": "user", "content": content}]))
    first, _, rest = answer.partition("\n")
    verdict = "APPROVE" if first.strip().strip("*").upper().startswith("APPROVE") else "REVISE"
    # Reasons are kept for both verdicts (printed, and saved as "Reviewer notes").
    result = {"verdict": verdict, "reasons": rest.strip()}
    handoff("reviewer", "coordinator", "verdict", result)
    return result


# ---------------------------------------------------------------------------
# Review step: write -> review (up to 2 revisions) -> name check -> save
# ---------------------------------------------------------------------------

def _review_loop(write, facts, recipient: str) -> tuple[str, dict, int]:
    draft = write(None, None)
    verdict = review(draft, facts, recipient)
    revisions = 0
    while verdict["verdict"] == "REVISE" and revisions < MAX_REVISIONS:
        revisions += 1
        print(f"    revision {revisions} of {MAX_REVISIONS}")
        draft = write(draft, verdict["reasons"])
        verdict = review(draft, facts, recipient)
    return draft, verdict, revisions


def _save(filename: str, header: dict, draft: str) -> Path:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / filename
    lines = [f"{k}: {v}" for k, v in header.items()]
    path.write_text("\n".join(lines) + "\n" + "-" * 60 + "\n" + draft.strip() + "\n", encoding="utf-8")
    print(f"    saved {path.relative_to(HERE.parent)}"
          + ("  ** NEEDS A PERSON **" if header["Needs a person"] != "no" else ""))
    return path


def draft_supplier_reply(email: str, brief: dict, email_name: str) -> dict:
    """Supplier writer + reviewer, the customer-name check, and the saved draft."""
    facts = supplier_view(brief)
    draft, verdict, revisions = _review_loop(
        lambda prev, notes: write_supplier_reply(email, brief, prev, notes), facts, "supplier")

    leaks = find_terms(draft, customer_terms())
    print(f"    name check (supplier draft): "
          + (f"FAILED, found {', '.join(leaks)}" if leaks else "passed, no customer named"))
    reasons = []
    if verdict["verdict"] != "APPROVE":
        reasons.append(f"reviewer still says REVISE after {revisions} revision(s)")
    if leaks:
        reasons.append("names a customer: " + ", ".join(leaks))

    part = next((p for p in read_csv("parts.csv") if p["part_id"] == brief.get("part_id")), {})
    contact = next((s for s in read_csv("suppliers.csv") if s["supplier"] == part.get("supplier")), {})
    header = {
        "To": f"{contact.get('contact_name', '?')} <{contact.get('contact_email', '?')}>"
              f" ({part.get('supplier', 'unknown supplier')})",
        "About": email_name,
        "Reviewer": verdict["verdict"], "Revisions": revisions,
        "Needs a person": "yes - " + "; ".join(reasons) if reasons else "no",
    }
    if verdict["reasons"]:
        header["Reviewer notes"] = " ".join(verdict["reasons"].split())
    path = _save(f"{email_name}__supplier-reply.txt", header, draft)
    return {"draft": draft, "path": str(path), "verdict": verdict["verdict"],
            "revisions": revisions, "needs_person": bool(reasons), "reasons": reasons}


def draft_customer_notice(order: dict, email_name: str) -> dict:
    """Customer writer + reviewer, the supplier-name check, and the saved draft."""
    facts = customer_view(order)
    draft, verdict, revisions = _review_loop(
        lambda prev, notes: write_customer_notice(order, prev, notes), facts, "customer")

    leaks = find_terms(draft, supplier_terms())
    print(f"    name check (customer draft {facts['order_id']}): "
          + (f"FAILED, found {', '.join(leaks)}" if leaks else "passed, no supplier named"))
    row = next((o for o in read_csv("orders.csv") if o["order_id"] == facts["order_id"]), {})
    reasons = []
    if verdict["verdict"] != "APPROVE":
        reasons.append(f"reviewer still says REVISE after {revisions} revision(s)")
    if leaks:
        reasons.append("names a supplier: " + ", ".join(leaks))
    if row.get("late_penalty", "").lower() == "yes":
        reasons.append("order has a late penalty")

    header = {
        "To": f"{row.get('customer', '?')} <{row.get('contact_email', '?')}>",
        "Order": facts["order_id"], "About": email_name,
        "Reviewer": verdict["verdict"], "Revisions": revisions,
        "Needs a person": "yes - " + "; ".join(reasons) if reasons else "no",
    }
    if verdict["reasons"]:
        header["Reviewer notes"] = " ".join(verdict["reasons"].split())
    path = _save(f"{email_name}__customer-{facts['order_id']}.txt", header, draft)
    return {"draft": draft, "path": str(path), "verdict": verdict["verdict"],
            "revisions": revisions, "needs_person": bool(reasons), "reasons": reasons}
