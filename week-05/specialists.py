"""The four specialists that the coordinators share (for any company; Brookfield by default).

Both coordinators (a fixed pipeline and an orchestrator agent) import this file, so the
specialists behave the same way no matter who calls them.

    run_analyst(email)                  agent with the supply_mcp_server.py tools; stops after
                                        10 tool calls; returns its brief as a dict (JSON)
    write_supplier_reply(email, brief)  one model call; customer names are removed first
    write_customer_notice(order)        one model call; sees only that one order's facts
    review(draft, facts, recipient[, email])  one model call; returns APPROVE or REVISE with reasons

    draft_supplier_reply(email, brief, email_name)   writer -> reviewer, up to 2 revisions,
    draft_customer_notice(order, email_name)         then the code name check, then save to
                                                     week-05/drafts

set_org(org) picks the company: its folder in week-05 (brookfield-bikes by default, or
copperline-coffee). Each specialist reads its system prompt from <folder>/prompts on every
call, so prompt edits take effect without a restart. Each company's drafts are saved in
week-05/drafts/<folder>.

After each review step the final draft is printed once, between a FINAL DRAFT TO
SUPPLIER (or FINAL DRAFT TO CUSTOMER <order_id>) line and a "Marked for a person: yes/no"
line. The analyst's brief is printed in full.

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
import supply_mcp_server as sd
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent                  # .../GBUS-652-Coursework/week-05
ORG = sd.DEFAULT_ORG                                    # company folder in week-05
COMPANY = sd.company_name(ORG)
PROMPTS_DIR = HERE / ORG / "prompts"
DRAFTS_DIR = HERE / "drafts" / ORG                      # each company's drafts in its own folder
SERVER = HERE / "supply_mcp_server.py"
KEY_FILE = HERE.parents[1] / "API-Key.txt"              # folder that contains the repo

MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 16000
MAX_TOOL_CALLS = 10                                     # analyst limit
MAX_REVISIONS = 2                                       # redrafts after a REVISE

# Server-side refusal fallback: if the model declines a request, the API retries it on a
# fallback model it picks by refusal category, so a draft still comes back.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def set_org(org: str) -> None:
    """Point the specialists (and the supply tools) at one company's folder."""
    global ORG, COMPANY, PROMPTS_DIR, DRAFTS_DIR
    sd.set_org(org)                                     # ValueError for an unknown folder
    ORG, COMPANY = org, sd.company_name(org)
    PROMPTS_DIR = HERE / org / "prompts"
    DRAFTS_DIR = HERE / "drafts" / org


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
    """One of the company's CSV files, with the standard column names added (product,
    units, ship_day, ...), whatever this company calls them."""
    return sd.read_table(name)


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
    server = StdioServerParameters(command=sys.executable, args=[str(SERVER), "--org", ORG],
                                   cwd=str(HERE.parent))
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
                        if tu.name == "check_coverage" and not is_error:
                            try:
                                COVERAGE_CHECKS.append(json.loads(text))
                            except json.JSONDecodeError:
                                pass
                        results.append({"type": "tool_result", "tool_use_id": tu.id,
                                        "content": text, "is_error": is_error})
                    if calls >= MAX_TOOL_CALLS:
                        results.append({"type": "text", "text": f"You have used all {MAX_TOOL_CALLS} "
                                        "tool calls. Write your brief as JSON now."})
                    messages.append({"role": "user", "content": results})


def run_analyst(email: str, sender: str = "coordinator") -> dict:
    """Work out how a supplier email affects customer orders. Returns the brief (a dict)."""
    handoff(sender, "analyst", "supplier email", email)
    COVERAGE_CHECKS.clear()
    brief = asyncio.run(_run_analyst(email))
    handoff("analyst", sender, "brief (in full)", brief)
    return brief


# ---------------------------------------------------------------------------
# Redacted views for the writers
# ---------------------------------------------------------------------------

# Every successful check_coverage result from the analyst's last run (one email per run).
# supplier_view uses them to give the supplier writer each option's impact in units and days.
COVERAGE_CHECKS: list[dict] = []


def impact_of(check: dict) -> dict:
    """Units short and days late for one check_coverage result, with no order details.

    units_short is the largest gap, on any order's ship day, between the units needed by that
    day (that order plus every order ahead of it) and the supply available by then. Adding up
    each order's units_short would count the same missing units more than once.
    """
    steps = [(0, check.get("on_hand", 0))]
    for a in sorted(check.get("arrivals_used", []), key=lambda a: a["arrives_in_days"]):
        steps.append((a["arrives_in_days"], steps[-1][1] + a["qty"]))
    needed, gap, late, never = 0, 0, 0, False
    for o in check.get("orders", []):
        needed += o["units_needed"]
        if o.get("status") == "short":
            supply = max(total for d, total in steps if d <= o["ship_day"])
            gap = max(gap, needed - supply)
            if o.get("days_late") is None:
                never = True
            else:
                late = max(late, o["days_late"])
    return {"units_short": gap, "days_late": None if never else late}


def impact_for(order_ids: list) -> dict:
    """The impact of the analyst's latest coverage check whose orders at risk are order_ids."""
    want = {str(i).upper() for i in order_ids}
    for check in reversed(COVERAGE_CHECKS):
        got = {str(i).upper() for i in check.get("summary", {}).get("orders_at_risk", [])}
        if got == want:
            return impact_of(check)
    if not want:
        return {"units_short": 0, "days_late": 0}
    return {"units_short": None, "days_late": None}     # no matching tool result: not known


def supplier_view(brief: dict) -> dict:
    """The brief with every customer name, order number, customer email and order detail removed.

    The supplier writer gets the impact in units short and days late (its prompt allows that),
    per option when the supplier offers options, but nothing about any single customer order.
    """
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

    def orders_in_option(option: dict) -> list:
        # The analyst names this list order_ids, order_ids_at_risk, orders_at_risk, ...
        for key, value in option.items():
            if isinstance(value, list) and ("order" in key or "risk" in key):
                return value
        return []

    options = [{"name": o.get("name"), **impact_for(orders_in_option(o))}
               for o in brief.get("options", []) if isinstance(o, dict)]
    view = {"part_id": brief.get("part_id"), "what_changed": brief.get("what_changed")}
    if options:
        # Only per-option figures: one overall figure would be true for one option only.
        view["options"] = options
    else:
        view["impact"] = impact_for([o.get("order_id") for o in brief.get("orders_at_risk", [])])
    view["note"] = ("units_short: most units missing at any point; days_late: most days any "
                    "order ships late; null means not known.")
    # decisions_for_a_person is left out on purpose: it is the analyst's notes for the company
    # and describes individual customer orders (shortfalls, lateness, penalties) even with the
    # names removed. The writer only needs to know that the company still has to decide.
    view[f"{COMPANY.split()[0].lower()}_must_decide"] = bool(brief.get("decisions_for_a_person"))
    view["supplier_questions"] = brief.get("supplier_questions", [])
    return scrub(view)


def customer_view(order: dict) -> dict:
    """Only this order's facts: no supplier, contact, PO, penalty, or other customer."""
    row = next((o for o in read_csv("orders.csv") if o["order_id"] == order.get("order_id")), {})
    ship, ready = order.get("ship_day"), order.get("ready_day")
    return {
        "order_id": order.get("order_id"),
        "customer": row.get("customer") or order.get("customer"),
        "product": row.get("product"),
        "quantity": int(row["units"]) if row.get("units") else None,
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


def review(draft: str, facts, recipient: str, email: str | None = None) -> dict:
    """One model call. Returns {"verdict": "APPROVE"|"REVISE", "reasons": str}.

    recipient is "supplier" or "customer". email is the supplier email being answered; it is
    passed only for supplier drafts, so the reviewer can check names and details taken from it
    (it holds no customer data, so the redaction is unchanged). The verdict is always exactly
    APPROVE or REVISE, and reasons is never empty. Anything other than a clear APPROVE is REVISE.
    """
    if recipient not in ("supplier", "customer"):
        raise ValueError(f"review(): recipient must be 'supplier' or 'customer', not {recipient!r}")
    handoff("coordinator", "reviewer", f"{recipient} draft + facts" + (" + supplier email" if email else ""),
            {"draft": draft, "facts": facts})
    email_block = (f"Supplier email this draft replies to (its own details, such as the sender's "
                   f"name, may be used in the draft):\n\n{email}\n\n" if email else "")
    content = (f"Recipient: {recipient}\n\n{email_block}Facts:\n{json.dumps(facts, indent=2)}\n\n"
               f"Draft:\n{draft}\n\nGive your reasons for either verdict. For APPROVE, say "
               "briefly why the draft passes each rule.")
    answer = text_of(call_model("reviewer", load_prompt("reviewer"),
                                [{"role": "user", "content": content}]))

    # The prompt asks for APPROVE or REVISE on the first line. Accept small format slips
    # ("**APPROVE**", "Verdict: REVISE", "APPROVE."), but a missing or mixed verdict is REVISE.
    first, _, rest = answer.partition("\n")
    words = set(re.findall(r"[A-Z]+", first.upper()))
    unclear = ("APPROVE" in words) == ("REVISE" in words)  # neither, or both
    if unclear:
        verdict, rest = "REVISE", answer  # keep the whole answer as the reasons
    else:
        verdict = "APPROVE" if "APPROVE" in words else "REVISE"
    reasons = rest.strip() or (
        "The reviewer gave no reasons." if verdict == "APPROVE"
        else "The reviewer said REVISE but gave no reasons. Check the draft against every rule.")
    if unclear:
        reasons = "The reviewer's answer had no clear APPROVE/REVISE line. " + reasons
    # Reasons are kept for both verdicts (printed, and saved as "Reviewer notes").
    result = {"verdict": verdict, "reasons": reasons}
    handoff("reviewer", "coordinator", "verdict", result)
    return result


# ---------------------------------------------------------------------------
# Review step: write -> review (up to 2 revisions) -> name check -> save
# ---------------------------------------------------------------------------

def _review_loop(write, facts, recipient: str, email: str | None = None) -> tuple[str, dict, int]:
    draft = write(None, None)
    verdict = review(draft, facts, recipient, email)
    revisions = 0
    while verdict["verdict"] == "REVISE" and revisions < MAX_REVISIONS:
        revisions += 1
        print(f"    revision {revisions} of {MAX_REVISIONS}")
        draft = write(draft, verdict["reasons"])
        verdict = review(draft, facts, recipient, email)
    return draft, verdict, revisions


def print_final(title: str, draft: str, needs_person: bool) -> None:
    """Print the final draft once, after the review step."""
    print(f"\n{title}")
    print(draft.strip())
    print(f"Marked for a person: {'yes' if needs_person else 'no'}")


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
        lambda prev, notes: write_supplier_reply(email, brief, prev, notes), facts, "supplier", email)

    leaks = find_terms(draft, customer_terms())
    print(f"    name check (supplier draft): "
          + (f"FAILED, found {', '.join(leaks)}" if leaks else "passed, no customer named"))
    reasons = []
    if verdict["verdict"] != "APPROVE":
        reasons.append(f"reviewer still says REVISE after {revisions} revision(s)")
    if leaks:
        reasons.append("names a customer: " + ", ".join(leaks))
    # The analyst listed decisions only a person can make (e.g. choosing a supplier's option),
    # so the reply can't go out until someone has decided.
    if brief.get("decisions_for_a_person"):
        reasons.append(f"{COMPANY} must make a decision first (see Decisions for a person)")

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
    print_final("FINAL DRAFT TO SUPPLIER", draft, bool(reasons))
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
    print_final(f"FINAL DRAFT TO CUSTOMER {facts['order_id']}", draft, bool(reasons))
    return {"draft": draft, "path": str(path), "verdict": verdict["verdict"],
            "revisions": revisions, "needs_person": bool(reasons), "reasons": reasons}
