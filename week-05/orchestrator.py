"""Agent coordinator for Brookfield Bicycle Company's supplier emails.

Unlike pipeline.py (fixed order), here Claude decides which specialists to use. The agent
gets the system prompt in week-05/brookfield-bikes/prompts/orchestrator.txt and four tools:

  run_supply_analyst       runs the supply analyst on the email; returns its brief
  draft_supplier_reply     drafts the supplier reply from the analyst's brief (no input)
  draft_customer_notice    drafts a notice for ONE order at risk (input: order_id only)
  finish                   ends the job: a summary for a person, and whether a person
                           must make a decision

The tools take no free text, so the orchestrator can't pass customer names to the supplier
writer or anything else to the writers: the code hands each specialist only what it should
see (see specialists.py). Every draft goes through the same review step as the pipeline
(writer -> reviewer, up to 2 revisions, code name check, saved in week-05/drafts).

The agent stops after 10 tool calls. Each choice it makes is printed, and at the end the
same summary as pipeline.py. Nothing is sent.

Run from the top of the repository:
    .venv\\Scripts\\python.exe week-05\\orchestrator.py --email week-05\\brookfield-bikes\\supplier-emails\\02-kendall-tire-options.eml
    .venv\\Scripts\\python.exe week-05\\orchestrator.py --email <file> --save week-05\\runs\\02-orchestrator.txt
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pipeline as p
import specialists as s

MAX_TOOL_CALLS = 10

TOOLS = [
    {
        "name": "run_supply_analyst",
        "description": "Run the supply analyst on the supplier email. It looks up stock, scheduled "
                       "shipments and open orders, and returns a brief: what changed, the orders at "
                       "risk, any options, decisions for a person, and the supplier's questions. "
                       "Run it before drafting anything.",
        "input_schema": {"type": "object", "properties": {}, "required": [],
                         "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "draft_supplier_reply",
        "description": "Draft a reply to the supplier from the analyst's brief. The draft is "
                       "reviewed and saved for a person to check; it is never sent. Needs the "
                       "analyst's brief first. Returns the review result and the draft.",
        "input_schema": {"type": "object", "properties": {}, "required": [],
                         "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "draft_customer_notice",
        "description": "Draft a notice to the customer of ONE order at risk, given only that "
                       "order's facts. The draft is reviewed and saved for a person to check; it "
                       "is never sent. The order must be in the analyst's orders_at_risk. "
                       "Returns the review result and the draft.",
        "input_schema": {"type": "object",
                         "properties": {"order_id": {"type": "string",
                                                     "description": "An order_id from the brief's orders_at_risk, such as O-1043."}},
                         "required": ["order_id"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "finish",
        "description": "End the job. Give a short summary for Brookfield's purchasing manager and "
                       "say whether a person needs to make a decision.",
        "input_schema": {"type": "object",
                         "properties": {
                             "summary": {"type": "string",
                                         "description": "A short summary for the purchasing manager."},
                             "decision_needed": {"type": "boolean",
                                                 "description": "True if a person must make a decision."}},
                         "required": ["summary", "decision_needed"], "additionalProperties": False},
        "strict": True,
    },
]


class Job:
    """State for one email: the brief, the drafts, and the finish result."""

    def __init__(self, email_path: Path):
        self.email = s.read_email(email_path)
        self.name = email_path.stem
        self.brief: dict | None = None
        self.drafts: list[dict] = []
        self.drafted: set[str] = set()              # "supplier" and order_ids already drafted
        self.finish: dict | None = None

    # Each tool returns (result text for the agent, is_error).

    def run_supply_analyst(self, _args: dict) -> tuple[str, bool]:
        if self.brief is not None:
            return "The analyst already ran. Its brief:\n" + json.dumps(self.brief, indent=2), False
        self.brief = s.run_analyst(self.email, sender="orchestrator")
        return json.dumps(self.brief, indent=2, ensure_ascii=False), False

    def draft_supplier_reply(self, _args: dict) -> tuple[str, bool]:
        if self.brief is None:
            return "No brief yet. Call run_supply_analyst first.", True
        if "supplier" in self.drafted:
            return "The supplier reply was already drafted and saved.", True
        result = s.draft_supplier_reply(self.email, self.brief, self.name)
        self.drafted.add("supplier")
        self.drafts.append({"kind": "supplier reply", **result})
        return draft_report(result), False

    def draft_customer_notice(self, args: dict) -> tuple[str, bool]:
        if self.brief is None:
            return "No brief yet. Call run_supply_analyst first.", True
        order_id = str(args.get("order_id", "")).strip().upper()
        at_risk = {str(o.get("order_id", "")).upper(): o for o in self.brief.get("orders_at_risk", [])}
        if order_id not in at_risk:
            known = ", ".join(at_risk) or "none"
            return f"{order_id or '(blank)'} is not an order at risk. Orders at risk: {known}.", True
        if order_id in self.drafted:
            return f"A notice for {order_id} was already drafted and saved.", True
        result = s.draft_customer_notice(at_risk[order_id], self.name)
        self.drafted.add(order_id)
        self.drafts.append({"kind": f"customer notice {order_id}", **result})
        return draft_report(result), False

    def finish_job(self, args: dict) -> tuple[str, bool]:
        summary = args.get("summary")
        needed = args.get("decision_needed")
        if not isinstance(summary, str) or not summary.strip() or not isinstance(needed, bool):
            return "finish needs summary (text) and decision_needed (true or false).", True
        self.finish = {"summary": summary.strip(), "decision_needed": needed}
        return "Job finished.", False


def draft_report(result: dict) -> str:
    return json.dumps({
        "saved_to": str(Path(result["path"]).relative_to(s.HERE.parent)),
        "reviewer_verdict": result["verdict"],
        "revisions": result["revisions"],
        "marked_for_a_person": result["needs_person"],
        "reasons": result["reasons"],
        "draft": result["draft"],
    }, indent=2, ensure_ascii=False)


def run(email_path: Path) -> None:
    job = Job(email_path)
    print(f"Brookfield orchestrator - {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print(f"Email:  {email_path.name}")
    print(f"Model:  {s.MODEL}")
    print(f"Tools:  {', '.join(t['name'] for t in TOOLS)} (at most {MAX_TOOL_CALLS} calls)")

    handlers = {"run_supply_analyst": job.run_supply_analyst,
                "draft_supplier_reply": job.draft_supplier_reply,
                "draft_customer_notice": job.draft_customer_notice,
                "finish": job.finish_job}
    messages: list = [{"role": "user", "content": f"Supplier email:\n\n{job.email}"}]
    calls, stopped, end = 0, "", ""
    try:
        while True:
            response = s.call_model("orchestrator", s.load_prompt("orchestrator"), messages, TOOLS)
            text = s.text_of(response)
            if text:
                print(f"\n[orchestrator] {text}")
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                end = "The orchestrator stopped without calling finish."
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for tu in tool_uses:
                if calls >= MAX_TOOL_CALLS or job.finish:
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "is_error": True,
                                    "content": "Not run: the job has ended."})
                    continue
                calls += 1
                args = tu.input if isinstance(tu.input, dict) else {}
                p.section(f"Choice {calls} of at most {MAX_TOOL_CALLS}: {tu.name}"
                          + (f"({json.dumps(args, ensure_ascii=False)})" if args else "()"))
                handler = handlers.get(tu.name)
                if handler is None:
                    content, is_error = f"Unknown tool: {tu.name}", True
                else:
                    content, is_error = handler(args)
                if is_error:
                    print(f"    refused: {content}")
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": content, "is_error": is_error})
            if job.finish:
                end = "The orchestrator called finish."
                break
            if calls >= MAX_TOOL_CALLS:
                end = f"Reached the limit of {MAX_TOOL_CALLS} tool calls without finish."
                break
            messages.append({"role": "user", "content": results})
    except p.STOP_ERRORS as exc:
        stopped = p.stop_message(exc)

    p.section("Orchestrator's result")
    print(f"Ended: {end or 'stopped by an error (see below)'}")
    print(f"Tool calls: {calls}")
    if job.finish:
        print(f"Decision needed by a person: {'yes' if job.finish['decision_needed'] else 'no'}")
        print(f"Summary for a person:\n  {job.finish['summary']}")
    else:
        print("No finish summary.")
    p.print_summary(job.drafts, job.brief, stopped)


def main() -> None:
    p.cli("Let Claude choose Brookfield's specialists for one supplier email. Sends nothing.", run)


if __name__ == "__main__":
    main()
