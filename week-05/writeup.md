## What I Built

I built a team of four Claude specialists (claude-sonnet-5-5) that prepares a company's response to one supplier email. The supply analyst is an agent that uses three MCP tools (get_part, get_orders_for_part, check_coverage) to work out which customer orders are at risk. The supplier writer and the customer writer each draft one email, and a reviewer approves each draft or sends it back, with up to two revisions. All four specialists live in one shared file, specialists.py, and two coordinators use them: pipeline.py runs them in a fixed order, and orchestrator.py lets Claude choose which specialist to call next. Redaction is done in code in both directions: the supplier writer never sees customer names or order details, the customer writer never sees the supplier's name, contact or PO number, and after review a code check scans every draft for leaks. To make the team work for Copperline, I added --org to all four Python files (default brookfield-bikes), so each company's data, prompts and drafts folder are picked by name, and I made the MCP server detect the CSV columns from their headers and values instead of assuming names, because Copperline's files use product, per_unit, units and ship_by_day where Brookfield's use different names. I ran all four Copperline emails through both coordinators and saved the eight runs in week-05/runs (copperline-01 to copperline-04, each as -pipeline and -orchestrator). Every brief found the orders I expected: O-2203, O-2204 and O-2205 for email 1; O-2205 under Option A and O-2203 under Option B for email 2; and none for emails 3 and 4.

## Why This Approach

Task A: Agent. The steps change from email to email: the agent reads the café's message, looks up its order to see which machine it bought and when, and only then knows whether it needs the warranty terms (a machine still under warranty is handled differently from one long out of it); if a result raises a new question it looks again, and then it drafts the reply. Because which lookups to make, and in what order, depends on what each result shows, the model needs tools it can choose between and call in a loop, which is an agent. A script can't read a free-text complaint or write a reply, one model call can't look anything up, and a team isn't needed because there is one reply to one customer and no information to keep apart.

Task B: Team. The task has three different jobs: first, trace the failed part through the bill of materials and shipping records to find every machine that already shipped with it and who received it; second, draft a separate notice to each affected customer that covers only that customer's machines and what to do next; third, draft a formal report for the safety regulator with the full facts (the part, the failed test, every affected machine and customer). Each job needs its own instructions and should see different information, because a customer must never see another customer's details while the regulator needs the complete list, and every draft should be reviewed before a person approves it. A team of specialists (an analyst with the lookup tools, a customer-notice writer, a report writer and a reviewer) gives each job its own instructions and only the facts it needs, the same way my Copperline team keeps customer and supplier details apart.

Task C: Pipeline. Every wholesale order needs the same three steps in the same order: check stock for each part in the order, draft the order confirmation from that result, then review the draft. Nothing has to be decided about what comes next, so a fixed sequence in code does the job: it spends no model calls on planning, runs the same way every time, and is easy to check and audit. My Copperline runs showed the trade-off: a pipeline always runs every step, which only wastes calls when some inputs need fewer steps (as email 4 did), and here every order needs all three.

Task D: Orchestrator. Each kind of email needs different steps: a supplier delay needs the supply analyst, a supplier reply and possibly customer notices; a price change needs a cost check and maybe a reply to the supplier; a customer complaint needs an order lookup and a customer reply; a sales lead needs only a sales reply. A fixed pipeline would either run steps an email doesn't need or need a new branch coded for every kind of email, and new kinds keep arriving. An orchestrator reads each email and calls only the specialists that email needs, in the order it needs them, and adding a new specialist as a tool lets it handle a new kind of email; in my email 4 run it called only the analyst and finished, while the pipeline ran all three steps.

## Example Run

```
Copperline Coffee Machines pipeline - 2026-11-17 16:41
Org:    copperline-coffee (drafts in week-05\drafts\copperline-coffee)
Columns found:
        bill-of-materials.csv: product = product, per_unit = per_unit
        orders.csv: product = product, units = units, ship_day = ship_by_day
Email:  03-ashgrove-burr-delay.eml
Model:  claude-sonnet-5-5
Order:  1. supply analyst  2. customer notices  3. supplier reply

======================================================================
Step 1 of 3: supply analyst
======================================================================

>>> HANDOFF  pipeline -> analyst: supplier email
    | From: Priya Raman <p.raman@ashgroveprecision.example>
    | To: Purchasing <purchasing@copperlinecoffee.example>
    | Subject: PO-5531 - BR-64 burr sets - arriving 3 days late
    | 
    | Hello,
    | 
    | A heat-treatment furnace at our plant needed an unplanned repair, so PO-5531
    | for 120 BR-64 burr sets will arrive 3 days after the scheduled date. The full
    | quantity will ship together.
    | 
    | Please let me know if this causes any problems on your side.
    | 
    | Best,
    | Priya Raman
    | Order Management, Ashgrove Precision
    analyst tools: get_part, get_orders_for_part, check_coverage
    [tokens] analyst: 2,001 in, 106 out (running total 2,001 in, 106 out)

>>> HANDOFF  analyst -> MCP tool get_part: tool call 1
    | {
    |   "part_id": "BR-64"
    | }

>>> HANDOFF  MCP tool get_part -> analyst: tool result
    | {
    |   "part_id": "BR-64",
    |   "description": "64 mm burr set",
    |   "supplier": "Ashgrove Precision",
    |   "on_hand": 70,
    |   "scheduled_shipments": [
    |     {
    |       "po_number": "PO-5531",
    |       "supplier": "Ashgrove Precision",
    |       "qty": 120,
    |       "arrives_in_days": 10
    |     }
    |   ],
    |   "total_scheduled": 120,
    |   "used_in_products": [
    |     {
    |       "product": "Grinder 64",
    |       "parts_per_unit": 1
    |     }
    |   ]
    | }

>>> HANDOFF  analyst -> MCP tool get_orders_for_part: tool call 2
    | {
    |   "part_id": "BR-64"
    | }

>>> HANDOFF  MCP tool get_orders_for_part -> analyst: tool result
    | {
    |   "part_id": "BR-64",
    |   "orders": [
    |     {
    |       "order_id": "O-2206",
    |       "customer": "Grindstone Coffee Bar",
    |       "product": "Grinder 64",
    |       "units_ordered": 30,
    |       "parts_per_unit": 1,
    |       "units_needed": 30,
    |       "ship_day": 8,
    |       "late_penalty": false
    |     },
    |     {
    |       "order_id": "O-2207",
    |       "customer": "Union Market Grocers",
    |       "product": "Grinder 64",
    |       "units_ordered": 60,
    |       "parts_per_unit": 1,
    |       "units_needed": 60,
    |       "ship_day": 14,
    |       "late_penalty": true
    |     },
    |     {
    |       "order_id": "O-2209",
    |       "customer": "Saltmarsh Inn",
    |       "product": "Grinder 64",
    |       "units_ordered": 25,
    |       "parts_per_unit": 1,
    |       "units_needed": 25,
    |       "ship_day": 26,
    |       "late_penalty": false
    |     }
    |   ],
    |   "total_units_needed": 115
    | }
    [tokens] analyst: 2,726 in, 106 out (running total 4,727 in, 212 out)

>>> HANDOFF  analyst -> MCP tool check_coverage: tool call 3
    | {
    |   "part_id": "BR-64",
    |   "arrivals": [
    |     {
    |       "qty": 120,
    |       "arrives_in_days": 13
    |     }
    |   ]
    | }

>>> HANDOFF  MCP tool check_coverage -> analyst: tool result
    | {
    |   "part_id": "BR-64",
    |   "on_hand": 70,
    |   "arrivals_used": [
    |     {
    |       "qty": 120,
    |       "arrives_in_days": 13
    |     }
    |   ],
    |   "orders": [
    |     {
    |       "order_id": "O-2206",
    |       "customer": "Grindstone Coffee Bar",
    |       "product": "Grinder 64",
    |       "units_needed": 30,
    |       "ship_day": 8,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2207",
    |       "customer": "Union Market Grocers",
    |       "product": "Grinder 64",
    |       "units_needed": 60,
    |       "ship_day": 14,
    |       "late_penalty": true,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2209",
    |       "customer": "Saltmarsh Inn",
    |       "product": "Grinder 64",
    |       "units_needed": 25,
    |       "ship_day": 26,
    |       "late_penalty": false,
    |       "status": "covered"
    |     }
    |   ],
    |   "summary": {
    |     "orders_checked": 3,
    |     "orders_covered": 3,
    |     "orders_at_risk": [],
    |     "orders_at_risk_with_late_penalty": [],
    |     "total_units_needed": 115,
    |     "total_supply": 190,
    |     "units_left_over": 75
    |   }
    | }
    [tokens] analyst: 3,299 in, 197 out (running total 8,026 in, 409 out)
    analyst finished after 3 tool call(s)

>>> HANDOFF  analyst -> pipeline: brief (in full)
    | {
    |   "part_id": "BR-64",
    |   "what_changed": "PO-5531 (120 BR-64 burr sets, full quantity in one shipment) now arrives on day 13 instead of day 10.",
    |   "orders_at_risk": [],
    |   "options": [],
    |   "decisions_for_a_person": [],
    |   "supplier_questions": [
    |     "Priya asks Copperline to tell her whether the 3-day delay causes any problems. Coverage check result: it causes none. All three open orders (O-2206, O-2207, O-2209) are still covered."
    |   ]
    | }

======================================================================
Step 2 of 3: customer notices
======================================================================
No orders at risk; skipping customer notices.

======================================================================
Step 3 of 3: supplier reply
======================================================================

>>> HANDOFF  coordinator -> supplier writer: email + redacted brief
    | {
    |   "brief": {
    |     "part_id": "BR-64",
    |     "what_changed": "PO-5531 (120 BR-64 burr sets, full quantity in one shipment) now arrives on day 13 instead of day 10.",
    |     "impact": {
    |       "units_short": 0,
    |       "days_late": 0
    |     },
    |     "note": "units_short: most units missing at any point; days_late: most days any order ships late; null means not known.",
    |     "copperline_must_decide": false,
    |     "supplier_questions": [
    |       "Priya asks Copperline to tell her whether the 3-day delay causes any problems. Coverage check result: it causes none. All three open orders (a customer order, a customer order, a customer order) are still covered."
    |     ]
    |   },
    |   "reviewer_notes": null
    | }
    [tokens] supplier writer: 738 in, 402 out (running total 738 in, 402 out)

>>> HANDOFF  supplier writer -> coordinator: draft
    | Subject: RE: PO-5531 - BR-64 burr sets - arriving 3 days late
    | 
    | Hello Priya,
    | 
    | Thank you for letting us know. We understand that PO-5531 (120 BR-64 burr sets, full quantity in one shipment) will now arrive on day 13 instead of day 10, because of the furnace repair.
    | 
    | We checked the impact on our side. This 3-day delay leaves us 0 units short and delays no orders, so it causes no problem for us.
    | 
    | If the repair finishes early and you can ship sooner, please tell us. Please also tell us right away if the date moves again, as another slip could change this assessment.
    | 
    | Best regards,
    | Purchasing, Copperline Coffee Machines

>>> HANDOFF  coordinator -> reviewer: supplier draft + facts + supplier email
    | {
    |   "draft": "Subject: RE: PO-5531 - BR-64 burr sets - arriving 3 days late\n\nHello Priya,\n\nThank you for letting us know. We understand that PO-5531 (120 BR-64 burr sets, full quantity in one shipment) will now arrive on day 13 instead of day 10, because of the furnace repair.\n\nWe checked the impact on our side. This 3-day delay leaves us 0 units short and delays no orders, so it causes no problem for us.\n\nIf the repair finishes early and you can ship sooner, please tell us. Please also tell us right away if the date moves again, as another slip could change this assessment.\n\nBest regards,\nPurchasing, Copperline Coffee Machines",
    |   "facts": {
    |     "part_id": "BR-64",
    |     "what_changed": "PO-5531 (120 BR-64 burr sets, full quantity in one shipment) now arrives on day 13 instead of day 10.",
    |     "impact": {
    |       "units_short": 0,
    |       "days_late": 0
    |     },
    |     "note": "units_short: most units missing at any point; days_late: most days any order ships late; null means not known.",
    |     "copperline_must_decide": false,
    |     "supplier_questions": [
    |       "Priya asks Copperline to tell her whether the 3-day delay causes any problems. Coverage check result: it causes none. All three open orders (a customer order, a customer order, a customer order) are still covered."
    |     ]
    |   }
    | }
    [tokens] reviewer: 1,068 in, 463 out (running total 1,068 in, 463 out)

>>> HANDOFF  reviewer -> coordinator: verdict
    | {
    |   "verdict": "APPROVE",
    |   "reasons": "Rule 1: Every figure in the draft matches the facts: PO-5531, 120 BR-64 burr sets, day 13 versus day 10, and the 3-day delay (13 − 10). The \"0 units short\" figure comes straight from the impact data (units_short: 0). Nothing is invented.\n\nRule 2: The draft promises no dates, quantities, discounts, or credits. Its requests that Priya report an early ship date or any further slip are asks, not commitments. The statement that another slip \"could change this assessment\" is a caution, not a promise.\n\nRule 3: The draft names no customer and describes no customer's order. It says only that \"no orders\" are delayed, which is a generic statement. It does not reveal who the customers are or what they ordered, and the facts' own wording, \"a customer order, a customer order, a customer order\", carries no customer detail either.\n\nRule 4: Not applicable, since the recipient is a supplier.\n\nRule 5: The draft accepts no option, agrees to no cost, and cancels nothing. It acknowledges the delay and answers Priya's question about whether it causes problems. The facts say Copperline has no decision to make (copperline_must_decide: false), and the draft makes none.\n\nRule 6: The tone is firm and cooperative. It thanks Priya, answers her question directly, asks to hear about an earlier shipment, and asks to be told right away if the date moves again."
    | }
    name check (supplier draft): passed, no customer named
    saved week-05\drafts\copperline-coffee\03-ashgrove-burr-delay__supplier-reply.txt

FINAL DRAFT TO SUPPLIER
Subject: RE: PO-5531 - BR-64 burr sets - arriving 3 days late

Hello Priya,

Thank you for letting us know. We understand that PO-5531 (120 BR-64 burr sets, full quantity in one shipment) will now arrive on day 13 instead of day 10, because of the furnace repair.

We checked the impact on our side. This 3-day delay leaves us 0 units short and delays no orders, so it causes no problem for us.

If the repair finishes early and you can ship sooner, please tell us. Please also tell us right away if the date moves again, as another slip could change this assessment.

Best regards,
Purchasing, Copperline Coffee Machines
Marked for a person: no

======================================================================
Summary
======================================================================
Drafts saved (1):
  - supplier reply: week-05\drafts\copperline-coffee\03-ashgrove-burr-delay__supplier-reply.txt (reviewer APPROVE, 0 revision(s))

Drafts marked for a person (0):
  (none)

Decisions for a person (0):
  (none)

Tokens by specialist
  specialist         calls     input    output     total
  analyst                3     8,026       409     8,435
  supplier writer        1       738       402     1,140
  reviewer               1     1,068       463     1,531
  all                          9,832     1,274    11,106

Saved this output to C:\Users\mikes\OneDrive\Desktop\GBUS-652-Course\GBUS-652-Coursework\week-05\runs\copperline-03-pipeline.txt
```

## Reflection

Email 1 reading: Matches. Diane wrote that the other 160 pumps "will follow 15 days later", and the scheduled date for PO-5512 is day 4, so the brief's what_changed line correctly gave day 19 for them: "40 will arrive on day 4 as scheduled, and the other 160 will arrive on day 19 (15 days later)."

Email 1 customer names: No. The reply to Danforth named no customer. It declined Diane's request for a list of customer orders ("We don't share customer names or order details with suppliers, so we can't send that list") and gave only the overall impact instead: up to 55 units short and orders up to 7 days late.

Email 4 orchestrator: Supply analyst. The orchestrator called only the analyst, saw that nothing changed and no orders were at risk, and finished with no drafts. The pipeline ran all its steps on the same email: the analyst, then the supplier writer, which wrote "NO REPLY NEEDED", then the reviewer, which approved it, and it saved that as a draft.

### Fixes I made after reviewing the runs, and my decisions

After the first runs, the instructor's guidance was that we may investigate and improve our code or the analyst's instructions and then run an email again, since the saved files are what's checked, but we must not edit the emails, the data files or the saved runs, and must not write any email's answer into a prompt. I did these checks and made these decisions before saving the final eight runs.

**Checking the course files.** I compared every Copperline file with the original copperline-coffee.zip byte for byte. The four emails and five prompts were identical. Four CSVs (inbound, orders, parts and suppliers) differed only in their line endings: something had re-saved them with Windows line endings, but every value was the same. I also searched my code and prompts for order numbers, PO numbers, names and option labels from the emails and found none outside usage examples.

**Re-running email 2 in the pipeline.** The re-run showed five problems that needed a decision:

1. The supplier reply said "40 units short", which is only true under Option B; Option A leaves 5 short. The supplier writer only received the default option's shortfall. The reviewer first called the number customer order information and then approved a reworded version. My first choice was to remove the unit shortfall from what the supplier writer sees, but the instructor's supplier-writer prompt allows the writer to say how many units are short and how many days orders will be delayed. So my decision was to give the supplier writer each option's units short and days late, worked out in code from the analyst's check_coverage results, with no order numbers, customers or per-order details. The code finds the largest gap between units needed and supply, because adding up each order's shortfall can count the same missing units twice.
2. The supplier reviewer never saw the supplier's email, so it flagged details taken from it ("Hi Victor", "the welding cell") as not in the facts. My decision: pass the supplier email to the supplier reviewer. It holds no customer data, so the redaction is unchanged.
3. The supplier reply was "Marked for a person: no" even though Copperline had to choose an option within three business days. My decision: mark the supplier reply as needing a person whenever the analyst lists a decision for a person.
4. The customer notice only fits the default option: if Copperline picks Option A, the O-2203 notice is wrong and O-2205 needs one. My decision: assume the default option for now. The notice is already marked for a person, and the decisions for a person describe both options.
5. My decision: restore the four CSVs exactly as they are in the zip. The data was the same either way, but now every file matches the original.

After these changes, the email 2 pipeline gave the supplier writer "Option A: 5 units short, 4 days late" and "Option B: 40 units short, 1 day late", the reviewer approved the reply on the first pass, and both drafts were marked for a person.

6. **Re-running email 1 in the orchestrator.** The orchestrator drafted no customer notices for the three orders at risk. The analyst had worded a decision as "decide whether to warn these customers", and the orchestrator took that to mean it shouldn't draft them, even though a draft is never sent. My decision was to add a general rule to the draft_customer_notice tool description in orchestrator.py: drafting is not sending, so draft a notice for each order at risk, and let the person decide whether to send it when they review it. The rule names no email or order. On the re-run the orchestrator drafted all three notices, matching the pipeline.
7. **Running email 2 in the orchestrator.** The reviewer first rejected "orders would be delayed by up to 4 days" as describing customer orders, although the instructor's supplier-writer prompt allows it. The writer kept the wording, as its instructions say, and the same reviewer then approved it. The pipeline runs approved the same wording on the first pass. My decision was to leave this unchanged: the final draft is correct, and the only cost was one extra review round (about 7,000 tokens), but it shows the reviewer is not fully consistent.

**Two more things the runs showed.** For email 3, the analyst put the order numbers of the three covered orders into a field that goes to the supplier writer; the redaction code replaced each one with "a customer order" before the writer saw it, and the name check passed. For email 4, the orchestrator skipped the writer and reviewer but still used slightly more tokens than the pipeline (12,071 against 10,817), because its own planning calls cost more than the specialists it skipped.
