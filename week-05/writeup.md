## What I Built

I built a team of four Claude specialists (claude-sonnet-5-5) that prepares a company's response to one supplier email. The supply analyst is an agent that uses three MCP tools (get_part, get_orders_for_part, check_coverage) to work out which customer orders are at risk. The supplier writer and the customer writer each draft one email, and a reviewer approves each draft or sends it back, with up to two revisions. All four specialists live in one shared file, specialists.py, and two coordinators use them: pipeline.py runs them in a fixed order, and orchestrator.py lets Claude choose which specialist to call next. Redaction is done in code in both directions: the supplier writer never sees customer names or order details, the customer writer never sees the supplier's name, contact or PO number, and after review a code check scans every draft for leaks. To make the team work for Copperline, I added --org to all four Python files (default brookfield-bikes), so each company's data, prompts and drafts folder are picked by name, and I made the MCP server detect the CSV columns from their headers and values instead of assuming names, because Copperline's files use product, per_unit, units and ship_by_day where Brookfield's use different names. I ran all four Copperline emails through both coordinators and saved the eight runs in week-05/runs (copperline-01 to copperline-04, each as -pipeline and -orchestrator). Every brief found the orders I expected: O-2203, O-2204 and O-2205 for email 1; O-2205 under Option A and O-2203 under Option B for email 2; and none for emails 3 and 4.

## Why This Approach

Task A: Agent. One reply is drafted, but what has to be looked up changes from email to email (the café's order, the warranty terms, or both), so the model needs tools it can choose between and must decide from each result what to look up next.

Task B: Team. The job has distinct steps with different audiences: tracing the shipped machines, notices to each customer, and a formal report for the regulator. Separate specialists can each get only the facts they should see, and a reviewer can check every draft before a person signs off.

Task C: Pipeline. Every wholesale order goes through the same steps in the same order (check stock, draft the confirmation, review it), so a fixed sequence in code is cheaper, predictable and easy to audit, and nothing needs to be decided about what comes next.

Task D: Orchestrator. Each email needs a different mix of specialists, and new kinds of email keep arriving, so a fixed order would either waste calls or miss steps. An orchestrator can read each email and call only the specialists it needs.

## Example Run

```
Copperline Coffee Machines orchestrator - 2026-11-17 16:37
Org:    copperline-coffee (drafts in week-05\drafts\copperline-coffee)
Columns found:
        bill-of-materials.csv: product = product, per_unit = per_unit
        orders.csv: product = product, units = units, ship_day = ship_by_day
Email:  02-marlow-boiler-options.eml
Model:  claude-sonnet-5-5
Tools:  run_supply_analyst, draft_supplier_reply, draft_customer_notice, finish (at most 10 calls)
    [tokens] orchestrator: 1,503 in, 31 out (running total 1,503 in, 31 out)

======================================================================
Choice 1 of at most 10: run_supply_analyst()
======================================================================

>>> HANDOFF  orchestrator -> analyst: supplier email
    | From: Victor Lindqvist <v.lindqvist@marlowmetal.example>
    | To: Purchasing <purchasing@copperlinecoffee.example>
    | Subject: PO-5520 - BL-12 boilers - please choose a shipping option
    | 
    | Hi,
    | 
    | About PO-5520 for 200 BL-12 boilers: our welding cell is running at half
    | capacity this month, so we can't ship the whole order on time. We can offer
    | two options:
    | 
    | Option A: Ship 80 boilers on the scheduled date, and the remaining 120 two
    | weeks after that.
    | 
    | Option B: Ship all 200 boilers together, six days after the scheduled date.
    | 
    | Please let us know which option you'd like within three business days. If we
    | don't hear from you by then, we'll go with Option B.
    | 
    | Regards,
    | Victor Lindqvist
    | Sales Coordinator, Marlow Metalworks
    analyst tools: get_part, get_orders_for_part, check_coverage
    [tokens] analyst: 2,084 in, 106 out (running total 2,084 in, 106 out)

>>> HANDOFF  analyst -> MCP tool get_part: tool call 1
    | {
    |   "part_id": "BL-12"
    | }

>>> HANDOFF  MCP tool get_part -> analyst: tool result
    | {
    |   "part_id": "BL-12",
    |   "description": "1.2-liter boiler",
    |   "supplier": "Marlow Metalworks",
    |   "on_hand": 60,
    |   "scheduled_shipments": [
    |     {
    |       "po_number": "PO-5520",
    |       "supplier": "Marlow Metalworks",
    |       "qty": 200,
    |       "arrives_in_days": 7
    |     }
    |   ],
    |   "total_scheduled": 200,
    |   "used_in_products": [
    |     {
    |       "product": "Cafe One",
    |       "parts_per_unit": 1
    |     },
    |     {
    |       "product": "Cafe Duo",
    |       "parts_per_unit": 2
    |     }
    |   ]
    | }

>>> HANDOFF  analyst -> MCP tool get_orders_for_part: tool call 2
    | {
    |   "part_id": "BL-12"
    | }

>>> HANDOFF  MCP tool get_orders_for_part -> analyst: tool result
    | {
    |   "part_id": "BL-12",
    |   "orders": [
    |     {
    |       "order_id": "O-2201",
    |       "customer": "Morning Ritual Cafe",
    |       "product": "Cafe One",
    |       "units_ordered": 20,
    |       "parts_per_unit": 1,
    |       "units_needed": 20,
    |       "ship_day": 6,
    |       "late_penalty": false
    |     },
    |     {
    |       "order_id": "O-2202",
    |       "customer": "Harbor Hotel Group",
    |       "product": "Cafe Duo",
    |       "units_ordered": 15,
    |       "parts_per_unit": 2,
    |       "units_needed": 30,
    |       "ship_day": 9,
    |       "late_penalty": false
    |     },
    |     {
    |       "order_id": "O-2203",
    |       "customer": "Elm State University Dining",
    |       "product": "Cafe One",
    |       "units_ordered": 50,
    |       "parts_per_unit": 1,
    |       "units_needed": 50,
    |       "ship_day": 12,
    |       "late_penalty": true
    |     },
    |     {
    |       "order_id": "O-2204",
    |       "customer": "Kettle & Crumb Bakery",
    |       "product": "Cafe Duo",
    |       "units_ordered": 10,
    |       "parts_per_unit": 2,
    |       "units_needed": 20,
    |       "ship_day": 15,
    |       "late_penalty": false
    |     },
    |     {
    |       "order_id": "O-2205",
    |       "customer": "Tall Pines Coffee House",
    |       "product": "Cafe One",
    |       "units_ordered": 25,
    |       "parts_per_unit": 1,
    |       "units_needed": 25,
    |       "ship_day": 17,
    |       "late_penalty": true
    |     },
    |     {
    |       "order_id": "O-2208",
    |       "customer": "Northside Roasters",
    |       "product": "Cafe Duo",
    |       "units_ordered": 12,
    |       "parts_per_unit": 2,
    |       "units_needed": 24,
    |       "ship_day": 30,
    |       "late_penalty": false
    |     },
    |     {
    |       "order_id": "O-2210",
    |       "customer": "Bright Day Coworking",
    |       "product": "Cafe One",
    |       "units_ordered": 15,
    |       "parts_per_unit": 1,
    |       "units_needed": 15,
    |       "ship_day": 33,
    |       "late_penalty": false
    |     }
    |   ],
    |   "total_units_needed": 184
    | }
    [tokens] analyst: 3,273 in, 270 out (running total 5,357 in, 376 out)

>>> HANDOFF  analyst -> MCP tool check_coverage: tool call 3
    | {
    |   "part_id": "BL-12",
    |   "arrivals": [
    |     {
    |       "qty": 80,
    |       "arrives_in_days": 7
    |     },
    |     {
    |       "qty": 120,
    |       "arrives_in_days": 21
    |     }
    |   ]
    | }

>>> HANDOFF  MCP tool check_coverage -> analyst: tool result
    | {
    |   "part_id": "BL-12",
    |   "on_hand": 60,
    |   "arrivals_used": [
    |     {
    |       "qty": 80,
    |       "arrives_in_days": 7
    |     },
    |     {
    |       "qty": 120,
    |       "arrives_in_days": 21
    |     }
    |   ],
    |   "orders": [
    |     {
    |       "order_id": "O-2201",
    |       "customer": "Morning Ritual Cafe",
    |       "product": "Cafe One",
    |       "units_needed": 20,
    |       "ship_day": 6,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2202",
    |       "customer": "Harbor Hotel Group",
    |       "product": "Cafe Duo",
    |       "units_needed": 30,
    |       "ship_day": 9,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2203",
    |       "customer": "Elm State University Dining",
    |       "product": "Cafe One",
    |       "units_needed": 50,
    |       "ship_day": 12,
    |       "late_penalty": true,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2204",
    |       "customer": "Kettle & Crumb Bakery",
    |       "product": "Cafe Duo",
    |       "units_needed": 20,
    |       "ship_day": 15,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2205",
    |       "customer": "Tall Pines Coffee House",
    |       "product": "Cafe One",
    |       "units_needed": 25,
    |       "ship_day": 17,
    |       "late_penalty": true,
    |       "status": "short",
    |       "units_short": 5,
    |       "ready_day": 21,
    |       "days_late": 4
    |     },
    |     {
    |       "order_id": "O-2208",
    |       "customer": "Northside Roasters",
    |       "product": "Cafe Duo",
    |       "units_needed": 24,
    |       "ship_day": 30,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2210",
    |       "customer": "Bright Day Coworking",
    |       "product": "Cafe One",
    |       "units_needed": 15,
    |       "ship_day": 33,
    |       "late_penalty": false,
    |       "status": "covered"
    |     }
    |   ],
    |   "summary": {
    |     "orders_checked": 7,
    |     "orders_covered": 6,
    |     "orders_at_risk": [
    |       "O-2205"
    |     ],
    |     "orders_at_risk_with_late_penalty": [
    |       "O-2205"
    |     ],
    |     "total_units_needed": 184,
    |     "total_supply": 260,
    |     "units_left_over": 76
    |   }
    | }

>>> HANDOFF  analyst -> MCP tool check_coverage: tool call 4
    | {
    |   "part_id": "BL-12",
    |   "arrivals": [
    |     {
    |       "qty": 200,
    |       "arrives_in_days": 13
    |     }
    |   ]
    | }

>>> HANDOFF  MCP tool check_coverage -> analyst: tool result
    | {
    |   "part_id": "BL-12",
    |   "on_hand": 60,
    |   "arrivals_used": [
    |     {
    |       "qty": 200,
    |       "arrives_in_days": 13
    |     }
    |   ],
    |   "orders": [
    |     {
    |       "order_id": "O-2201",
    |       "customer": "Morning Ritual Cafe",
    |       "product": "Cafe One",
    |       "units_needed": 20,
    |       "ship_day": 6,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2202",
    |       "customer": "Harbor Hotel Group",
    |       "product": "Cafe Duo",
    |       "units_needed": 30,
    |       "ship_day": 9,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2203",
    |       "customer": "Elm State University Dining",
    |       "product": "Cafe One",
    |       "units_needed": 50,
    |       "ship_day": 12,
    |       "late_penalty": true,
    |       "status": "short",
    |       "units_short": 40,
    |       "ready_day": 13,
    |       "days_late": 1
    |     },
    |     {
    |       "order_id": "O-2204",
    |       "customer": "Kettle & Crumb Bakery",
    |       "product": "Cafe Duo",
    |       "units_needed": 20,
    |       "ship_day": 15,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2205",
    |       "customer": "Tall Pines Coffee House",
    |       "product": "Cafe One",
    |       "units_needed": 25,
    |       "ship_day": 17,
    |       "late_penalty": true,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2208",
    |       "customer": "Northside Roasters",
    |       "product": "Cafe Duo",
    |       "units_needed": 24,
    |       "ship_day": 30,
    |       "late_penalty": false,
    |       "status": "covered"
    |     },
    |     {
    |       "order_id": "O-2210",
    |       "customer": "Bright Day Coworking",
    |       "product": "Cafe One",
    |       "units_needed": 15,
    |       "ship_day": 33,
    |       "late_penalty": false,
    |       "status": "covered"
    |     }
    |   ],
    |   "summary": {
    |     "orders_checked": 7,
    |     "orders_covered": 6,
    |     "orders_at_risk": [
    |       "O-2203"
    |     ],
    |     "orders_at_risk_with_late_penalty": [
    |       "O-2203"
    |     ],
    |     "total_units_needed": 184,
    |     "total_supply": 260,
    |     "units_left_over": 76
    |   }
    | }
    [tokens] analyst: 5,392 in, 931 out (running total 10,749 in, 1,307 out)
    analyst finished after 4 tool call(s)

>>> HANDOFF  analyst -> orchestrator: brief (in full)
    | {
    |   "part_id": "BL-12",
    |   "what_changed": "PO-5520 (200 BL-12 boilers) was due on day 7. Marlow Metalworks can't ship it all on time and offers two options. Option A is 80 boilers on day 7 and 120 on day 21. Option B is all 200 on day 13. If Copperline doesn't reply, Marlow will ship Option B.",
    |   "orders_at_risk": [
    |     {
    |       "order_id": "O-2203",
    |       "customer": "Elm State University Dining",
    |       "units_short": 40,
    |       "ship_day": 12,
    |       "ready_day": 13,
    |       "late_penalty": true
    |     }
    |   ],
    |   "options": [
    |     {
    |       "name": "Option A: 80 units on day 7, 120 units on day 21",
    |       "order_ids_at_risk": [
    |         "O-2205"
    |       ]
    |     },
    |     {
    |       "name": "Option B: all 200 units on day 13 (the default if Copperline doesn't reply)",
    |       "order_ids_at_risk": [
    |         "O-2203"
    |       ]
    |     }
    |   ],
    |   "decisions_for_a_person": [
    |     "Choose Option A or Option B and tell Marlow within three business days. After that Marlow will ship Option B by default. The orders_at_risk list above shows Option B, the default.",
    |     "Option A puts O-2205 (Tall Pines Coffee House, late penalty) at risk. It would be 5 units short on its day-17 ship date and ready on day 21, which is 4 days late.",
    |     "Option B puts O-2203 (Elm State University Dining, late penalty) at risk. It would be 40 units short on its day-12 ship date and ready on day 13, which is 1 day late.",
    |     "Both at-risk orders have late penalties. Weigh a 4-day delay for Tall Pines (Option A) against a 1-day delay for Elm State (Option B)."
    |   ],
    |   "supplier_questions": [
    |     "Which option does Copperline want: Option A (80 units on the scheduled date, 120 units two weeks later) or Option B (all 200 units six days after the scheduled date)? Marlow needs an answer within three business days and will go with Option B if it hears nothing."
    |   ]
    | }
    [tokens] orchestrator: 2,278 in, 171 out (running total 3,781 in, 202 out)

======================================================================
Choice 2 of at most 10: draft_supplier_reply()
======================================================================

>>> HANDOFF  coordinator -> supplier writer: email + redacted brief
    | {
    |   "brief": {
    |     "part_id": "BL-12",
    |     "what_changed": "PO-5520 (200 BL-12 boilers) was due on day 7. Marlow Metalworks can't ship it all on time and offers two options. Option A is 80 boilers on day 7 and 120 on day 21. Option B is all 200 on day 13. If Copperline doesn't reply, Marlow will ship Option B.",
    |     "options": [
    |       {
    |         "name": "Option A: 80 units on day 7, 120 units on day 21",
    |         "units_short": 5,
    |         "days_late": 4
    |       },
    |       {
    |         "name": "Option B: all 200 units on day 13 (the default if Copperline doesn't reply)",
    |         "units_short": 40,
    |         "days_late": 1
    |       }
    |     ],
    |     "note": "units_short: most units missing at any point; days_late: most days any order ships late; null means not known.",
    |     "copperline_must_decide": true,
    |     "supplier_questions": [
    |       "Which option does Copperline want: Option A (80 units on the scheduled date, 120 units two weeks later) or Option B (all 200 units six days after the scheduled date)? Marlow needs an answer within three business days and will go with Option B if it hears nothing."
    |     ]
    |   },
    |   "reviewer_notes": null
    | }
    [tokens] supplier writer: 997 in, 866 out (running total 997 in, 866 out)

>>> HANDOFF  supplier writer -> coordinator: draft
    | Subject: RE: PO-5520 - BL-12 boilers - please choose a shipping option
    | 
    | Hi Victor,
    | 
    | Thanks for letting us know about PO-5520. Here is our understanding of the change. Your welding cell is at half capacity, so the 200 BL-12 boilers can't all ship on the scheduled date. You've offered two options:
    | 
    | - **Option A:** 80 boilers on the scheduled date and the remaining 120 two weeks later. For us, that means we would be up to 5 units short and orders would be delayed by up to 4 days.
    | - **Option B:** all 200 boilers together, six days after the scheduled date. For us, that means we would be up to 40 units short and orders would be delayed by up to 1 day.
    | 
    | Any shortfall on this part directly delays our builds, so we'd like to reduce the impact wherever possible. Could you tell us:
    | 
    | 1. Under Option A, can you ship more than 80 boilers on the scheduled date, or bring the remaining shipment forward from two weeks later?
    | 2. Under Option B, can you ship any boilers earlier than six days after the scheduled date, for example a partial shipment sooner with the rest following?
    | 3. Is there any way to recover capacity in the welding cell, such as overtime or a second shift, to bring either option forward?
    | 
    | We will confirm our choice within the three business days you've asked for. Please don't treat this message as acceptance of either option. Any additional boilers you can ship sooner would help, so please send us what you can do on the above.
    | 
    | Regards,
    | Purchasing, Copperline Coffee Machines

>>> HANDOFF  coordinator -> reviewer: supplier draft + facts + supplier email
    | {
    |   "draft": "Subject: RE: PO-5520 - BL-12 boilers - please choose a shipping option\n\nHi Victor,\n\nThanks for letting us know about PO-5520. Here is our understanding of the change. Your welding cell is at half capacity, so the 200 BL-12 boilers can't all ship on the scheduled date. You've offered two options:\n\n- **Option A:** 80 boilers on the scheduled date and the remaining 120 two weeks later. For us, that means we would be up to 5 units short and orders would be delayed by up to 4 days.\n- **Option B:** all 200 boilers together, six days after the scheduled date. For us, that means we would be up to 40 units short and orders would be delayed by up to 1 day.\n\nAny shortfall on this part directly delays our builds, so we'd like to reduce the impact wherever possible. Could you tell us:\n\n1. Under Option A, can you ship more than 80 boilers on the scheduled date, or bring the remaining shipment forward from two weeks later?\n2. Under Option B, can you ship any boilers earlier than six days after the scheduled date, for example a partial shipment sooner with the rest following?\n3. Is there any way to recover capacity in the welding cell, such as overtime or a second shift, to bring either option forward?\n\nWe will confirm our choice within the three business days you've asked for. Please don't treat this message as acceptance of either option. Any additional boilers you can ship sooner would help, so please send us what you can do on the above.\n\nRegards,\nPurchasing, Copperline Coffee Machines",
    |   "facts": {
    |     "part_id": "BL-12",
    |     "what_changed": "PO-5520 (200 BL-12 boilers) was due on day 7. Marlow Metalworks can't ship it all on time and offers two options. Option A is 80 boilers on day 7 and 120 on day 21. Option B is all 200 on day 13. If Copperline doesn't reply, Marlow will ship Option B.",
    |     "options": [
    |       {
    |         "name": "Option A: 80 units on day 7, 120 units on day 21",
    |         "units_short": 5,
    |         "days_late": 4
    |       },
    |       {
    |         "name": "Option B: all 200 units on day 13 (the default if Copperline doesn't reply)",
    |         "units_short": 40,
    |         "days_late": 1
    |       }
    |     ],
    |     "note": "units_short: most units missing at any point; days_late: most days any order ships late; null means not known.",
    |     "copperline_must_decide": true,
    |     "supplier_questions": [
    |       "Which option does Copperline want: Option A (80 units on the scheduled date, 120 units two weeks later) or Option B (all 200 units six days after the scheduled date)? Marlow needs an answer within three business days and will go with Option B if it hears nothing."
    |     ]
    |   }
    | }
    [tokens] reviewer: 1,605 in, 1,844 out (running total 1,605 in, 1,844 out)

>>> HANDOFF  reviewer -> coordinator: verdict
    | {
    |   "verdict": "REVISE",
    |   "reasons": "**Rule 3 is broken.** The draft tells the supplier that \"orders would be delayed by up to 4 days\" under Option A and \"by up to 1 day\" under Option B. In the facts, `days_late` means \"most days any order ships late,\" so these are Copperline's customer orders. The draft is describing the effect on customer orders to a supplier, which this rule forbids.\n\n**What to change:**\n- Delete \"and orders would be delayed by up to 4 days\" from Option A, and \"and orders would be delayed by up to 1 day\" from Option B. Don't give the `days_late` figures to Marlow at all.\n- Keep the shortage figures if you like, e.g. \"we would be up to 5 units short.\" They describe Copperline's stock of the part, not a customer's order.\n- The \"1 day\" figure also sits oddly beside the supplier's own six-day delay on Option B, so dropping it avoids confusion.\n\n**Rules that pass:**\n- **Rule 1:** Every number (PO-5520, 200, 80, 120, 5, 40, 4, 1, two weeks, six days, three business days) comes from the facts or the supplier's email.\n- **Rule 2:** The draft promises no dates, quantities, discounts or credits. Confirming a choice within the three business days Marlow asked for is supported by the facts.\n- **Rule 4:** This is a supplier email, so the rule doesn't apply.\n- **Rule 5:** The draft accepts no option, agrees to no cost and cancels nothing. It states that the message is not an acceptance of either option.\n- **Rule 6:** The tone is firm and cooperative. It asks for improvements and capacity recovery without being hostile."
    | }
    revision 1 of 2

>>> HANDOFF  coordinator -> supplier writer: email + redacted brief + reviewer notes
    | {
    |   "brief": {
    |     "part_id": "BL-12",
    |     "what_changed": "PO-5520 (200 BL-12 boilers) was due on day 7. Marlow Metalworks can't ship it all on time and offers two options. Option A is 80 boilers on day 7 and 120 on day 21. Option B is all 200 on day 13. If Copperline doesn't reply, Marlow will ship Option B.",
    |     "options": [
    |       {
    |         "name": "Option A: 80 units on day 7, 120 units on day 21",
    |         "units_short": 5,
    |         "days_late": 4
    |       },
    |       {
    |         "name": "Option B: all 200 units on day 13 (the default if Copperline doesn't reply)",
    |         "units_short": 40,
    |         "days_late": 1
    |       }
    |     ],
    |     "note": "units_short: most units missing at any point; days_late: most days any order ships late; null means not known.",
    |     "copperline_must_decide": true,
    |     "supplier_questions": [
    |       "Which option does Copperline want: Option A (80 units on the scheduled date, 120 units two weeks later) or Option B (all 200 units six days after the scheduled date)? Marlow needs an answer within three business days and will go with Option B if it hears nothing."
    |     ]
    |   },
    |   "reviewer_notes": "**Rule 3 is broken.** The draft tells the supplier that \"orders would be delayed by up to 4 days\" under Option A and \"by up to 1 day\" under Option B. In the facts, `days_late` means \"most days any order ships late,\" so these are Copperline's customer orders. The draft is describing the effect on customer orders to a supplier, which this rule forbids.\n\n**What to change:**\n- Delete \"and orders would be delayed by up to 4 days\" from Option A, and \"and orders would be delayed by up to 1 day\" from Option B. Don't give the `days_late` figures to Marlow at all.\n- Keep the shortage figures if you like, e.g. \"we would be up to 5 units short.\" They describe Copperline's stock of the part, not a customer's order.\n- The \"1 day\" figure also sits oddly beside the supplier's own six-day delay on Option B, so dropping it avoids confusion.\n\n**Rules that pass:**\n- **Rule 1:** Every number (PO-5520, 200, 80, 120, 5, 40, 4, 1, two weeks, six days, three business days) comes from the facts or the supplier's email.\n- **Rule 2:** The draft promises no dates, quantities, discounts or credits. Confirming a choice within the three business days Marlow asked for is supported by the facts.\n- **Rule 4:** This is a supplier email, so the rule doesn't apply.\n- **Rule 5:** The draft accepts no option, agrees to no cost and cancels nothing. It states that the message is not an acceptance of either option.\n- **Rule 6:** The tone is firm and cooperative. It asks for improvements and capacity recovery without being hostile."
    | }
    [tokens] supplier writer: 2,133 in, 825 out (running total 3,130 in, 1,691 out)

>>> HANDOFF  supplier writer -> coordinator: draft
    | Subject: RE: PO-5520 - BL-12 boilers - please choose a shipping option
    | 
    | Hi Victor,
    | 
    | Thanks for letting us know about PO-5520. Here is our understanding of the change. Your welding cell is at half capacity, so the 200 BL-12 boilers can't all ship on the scheduled date. You've offered two options:
    | 
    | - **Option A:** 80 boilers on the scheduled date and the remaining 120 two weeks later. For us, that means we would be up to 5 units short and orders would be delayed by up to 4 days.
    | - **Option B:** all 200 boilers together, six days after the scheduled date. For us, that means we would be up to 40 units short and orders would be delayed by up to 1 day.
    | 
    | Any shortfall on this part directly delays our builds, so we'd like to reduce the impact wherever possible. Could you tell us:
    | 
    | 1. Under Option A, can you ship more than 80 boilers on the scheduled date, or bring the remaining shipment forward from two weeks later?
    | 2. Under Option B, can you ship any boilers earlier than six days after the scheduled date, for example a partial shipment sooner with the rest following?
    | 3. Is there any way to recover capacity in the welding cell, such as overtime or a second shift, to bring either option forward?
    | 
    | We will confirm our choice within the three business days you've asked for. Please don't treat this message as acceptance of either option. Any additional boilers you can ship sooner would help, so please send us what you can do on the above.
    | 
    | Regards,
    | Purchasing, Copperline Coffee Machines

>>> HANDOFF  coordinator -> reviewer: supplier draft + facts + supplier email
    | {
    |   "draft": "Subject: RE: PO-5520 - BL-12 boilers - please choose a shipping option\n\nHi Victor,\n\nThanks for letting us know about PO-5520. Here is our understanding of the change. Your welding cell is at half capacity, so the 200 BL-12 boilers can't all ship on the scheduled date. You've offered two options:\n\n- **Option A:** 80 boilers on the scheduled date and the remaining 120 two weeks later. For us, that means we would be up to 5 units short and orders would be delayed by up to 4 days.\n- **Option B:** all 200 boilers together, six days after the scheduled date. For us, that means we would be up to 40 units short and orders would be delayed by up to 1 day.\n\nAny shortfall on this part directly delays our builds, so we'd like to reduce the impact wherever possible. Could you tell us:\n\n1. Under Option A, can you ship more than 80 boilers on the scheduled date, or bring the remaining shipment forward from two weeks later?\n2. Under Option B, can you ship any boilers earlier than six days after the scheduled date, for example a partial shipment sooner with the rest following?\n3. Is there any way to recover capacity in the welding cell, such as overtime or a second shift, to bring either option forward?\n\nWe will confirm our choice within the three business days you've asked for. Please don't treat this message as acceptance of either option. Any additional boilers you can ship sooner would help, so please send us what you can do on the above.\n\nRegards,\nPurchasing, Copperline Coffee Machines",
    |   "facts": {
    |     "part_id": "BL-12",
    |     "what_changed": "PO-5520 (200 BL-12 boilers) was due on day 7. Marlow Metalworks can't ship it all on time and offers two options. Option A is 80 boilers on day 7 and 120 on day 21. Option B is all 200 on day 13. If Copperline doesn't reply, Marlow will ship Option B.",
    |     "options": [
    |       {
    |         "name": "Option A: 80 units on day 7, 120 units on day 21",
    |         "units_short": 5,
    |         "days_late": 4
    |       },
    |       {
    |         "name": "Option B: all 200 units on day 13 (the default if Copperline doesn't reply)",
    |         "units_short": 40,
    |         "days_late": 1
    |       }
    |     ],
    |     "note": "units_short: most units missing at any point; days_late: most days any order ships late; null means not known.",
    |     "copperline_must_decide": true,
    |     "supplier_questions": [
    |       "Which option does Copperline want: Option A (80 units on the scheduled date, 120 units two weeks later) or Option B (all 200 units six days after the scheduled date)? Marlow needs an answer within three business days and will go with Option B if it hears nothing."
    |     ]
    |   }
    | }
    [tokens] reviewer: 1,605 in, 1,674 out (running total 3,210 in, 3,518 out)

>>> HANDOFF  reviewer -> coordinator: verdict
    | {
    |   "verdict": "APPROVE",
    |   "reasons": "1. **Numbers:** Every figure traces to the facts or the supplier's email: PO-5520, 200 BL-12 boilers, 80 and 120 units, two weeks, six days (day 13 minus day 7), up to 5 and 40 units short, and up to 4 and 1 days of delay. The three business days come from Marlow's email.\n2. **No unsupported promises:** The draft promises no dates, quantities, discounts or credits. The \"confirm our choice within the three business days you've asked for\" line only echoes Marlow's stated deadline, and the facts say Copperline must decide. The questions about shipping more units sooner or recovering welding capacity are requests, not commitments.\n3. **No customer details:** The draft names no customer and describes no specific customer order. \"Orders would be delayed\" and \"delays our builds\" are general statements about the impact on Copperline, drawn from the facts' days_late and units_short.\n4. **Supplier-recipient check only:** Rule 4 applies only to customer emails, so it doesn't apply here.\n5. **No acceptance or cancellation:** The draft explicitly says \"Please don't treat this message as acceptance of either option.\" It agrees to no cost, and asking about overtime or a second shift is an inquiry only. It also doesn't choose Option A or B, which is correct because the decision hasn't been made.\n6. **Tone:** It is firm and cooperative. It restates the situation, explains the impact, asks for improvements, and keeps Copperline's position open.\n\nOptional wording tweak, not required: \"We will respond within the three business days\" would avoid even implying a promised decision."
    | }
    name check (supplier draft): passed, no customer named
    saved week-05\drafts\copperline-coffee\02-marlow-boiler-options__supplier-reply.txt  ** NEEDS A PERSON **

FINAL DRAFT TO SUPPLIER
Subject: RE: PO-5520 - BL-12 boilers - please choose a shipping option

Hi Victor,

Thanks for letting us know about PO-5520. Here is our understanding of the change. Your welding cell is at half capacity, so the 200 BL-12 boilers can't all ship on the scheduled date. You've offered two options:

- **Option A:** 80 boilers on the scheduled date and the remaining 120 two weeks later. For us, that means we would be up to 5 units short and orders would be delayed by up to 4 days.
- **Option B:** all 200 boilers together, six days after the scheduled date. For us, that means we would be up to 40 units short and orders would be delayed by up to 1 day.

Any shortfall on this part directly delays our builds, so we'd like to reduce the impact wherever possible. Could you tell us:

1. Under Option A, can you ship more than 80 boilers on the scheduled date, or bring the remaining shipment forward from two weeks later?
2. Under Option B, can you ship any boilers earlier than six days after the scheduled date, for example a partial shipment sooner with the rest following?
3. Is there any way to recover capacity in the welding cell, such as overtime or a second shift, to bring either option forward?

We will confirm our choice within the three business days you've asked for. Please don't treat this message as acceptance of either option. Any additional boilers you can ship sooner would help, so please send us what you can do on the above.

Regards,
Purchasing, Copperline Coffee Machines
Marked for a person: yes

======================================================================
Choice 3 of at most 10: draft_customer_notice({"order_id": "O-2203"})
======================================================================

>>> HANDOFF  coordinator -> customer writer: one order's facts
    | {
    |   "order": {
    |     "order_id": "O-2203",
    |     "customer": "Elm State University Dining",
    |     "product": "Cafe One",
    |     "quantity": 50,
    |     "planned_ship_day": 12,
    |     "expected_ship_day": 13,
    |     "days_late": 1,
    |     "cause": "a delay in a part from one of our suppliers",
    |     "note": "Days are counted from today (day 0). expected_ship_day null means not yet known."
    |   },
    |   "reviewer_notes": null
    | }
    [tokens] customer writer: 377 in, 182 out (running total 377 in, 182 out)

>>> HANDOFF  customer writer -> coordinator: draft
    | Subject: Update on Order O-2203
    | 
    | Dear Elm State University Dining team,
    | 
    | We're writing about your order O-2203 for 50 Cafe One machines. Because of a delay in a part from one of our suppliers, the order is now expected to ship 1 day later than planned.
    | 
    | We apologize for the inconvenience. We know you're counting on these machines, and we'll let you know if anything changes with this timing.
    | 
    | If you have questions about your order, please reply to this message and our team will be glad to help.
    | 
    | Sincerely,
    | Customer Service, Copperline Coffee Machines

>>> HANDOFF  coordinator -> reviewer: customer draft + facts
    | {
    |   "draft": "Subject: Update on Order O-2203\n\nDear Elm State University Dining team,\n\nWe're writing about your order O-2203 for 50 Cafe One machines. Because of a delay in a part from one of our suppliers, the order is now expected to ship 1 day later than planned.\n\nWe apologize for the inconvenience. We know you're counting on these machines, and we'll let you know if anything changes with this timing.\n\nIf you have questions about your order, please reply to this message and our team will be glad to help.\n\nSincerely,\nCustomer Service, Copperline Coffee Machines",
    |   "facts": {
    |     "order_id": "O-2203",
    |     "customer": "Elm State University Dining",
    |     "product": "Cafe One",
    |     "quantity": 50,
    |     "planned_ship_day": 12,
    |     "expected_ship_day": 13,
    |     "days_late": 1,
    |     "cause": "a delay in a part from one of our suppliers",
    |     "note": "Days are counted from today (day 0). expected_ship_day null means not yet known."
    |   }
    | }
    [tokens] reviewer: 698 in, 589 out (running total 3,908 in, 4,107 out)

>>> HANDOFF  reviewer -> coordinator: verdict
    | {
    |   "verdict": "APPROVE",
    |   "reasons": "1. **Numbers:** The order number O-2203, the quantity of 50 Cafe One machines, and the 1-day delay all appear in the facts. The delay matches days_late (13 − 12 = 1).\n2. **No unsupported promises:** The draft gives no ship date, quantity, discount, or credit. It only says the order is expected to ship 1 day later than planned, which the facts support. The offer to \"let you know if anything changes\" is a communication commitment, not one of the promises the rule restricts.\n3. **Supplier-facing restriction:** This rule doesn't apply, because the draft goes to a customer.\n4. **Customer restrictions:** The draft names no supplier. \"One of our suppliers\" is the generic cause given in the facts and identifies no one. It names no other customer and mentions no cost.\n5. **No acceptance or cancellation:** The draft doesn't accept an option, agree to a cost, or cancel anything.\n6. **Tone:** It is plain and apologetic, with a clear apology and an invitation to reply with questions. That suits a customer."
    | }
    name check (customer draft O-2203): passed, no supplier named
    saved week-05\drafts\copperline-coffee\02-marlow-boiler-options__customer-O-2203.txt  ** NEEDS A PERSON **

FINAL DRAFT TO CUSTOMER O-2203
Subject: Update on Order O-2203

Dear Elm State University Dining team,

We're writing about your order O-2203 for 50 Cafe One machines. Because of a delay in a part from one of our suppliers, the order is now expected to ship 1 day later than planned.

We apologize for the inconvenience. We know you're counting on these machines, and we'll let you know if anything changes with this timing.

If you have questions about your order, please reply to this message and our team will be glad to help.

Sincerely,
Customer Service, Copperline Coffee Machines
Marked for a person: yes
    [tokens] orchestrator: 3,518 in, 478 out (running total 7,299 in, 680 out)

======================================================================
Choice 4 of at most 10: finish({"summary": "Marlow can't ship PO-5520 (200 BL-12 boilers) on time and wants a choice of option within 3 business days. If we don't reply, Marlow ships Option B.\n- Option A: 80 units on day 7 and 120 on day 21. This puts O-2205 (Tall Pines Coffee House, late penalty) at risk. It would be 5 units short and 4 days late.\n- Option B (the default): all 200 units on day 13. This puts O-2203 (Elm State University Dining, late penalty) at risk. It would be 40 units short and 1 day late.\nDecision for you: choose A or B and tell Marlow before the deadline. Both at-risk orders carry late penalties.\nDrafts saved for your review, none sent:\n- Reply to Marlow. It asks about earlier or partial shipments and extra welding capacity, and it doesn't accept either option.\n- Notice to Elm State for O-2203. This notice assumes Option B. Send it only if you pick B or let the default apply.\nNo notice is drafted for O-2205 (Tall Pines). The analyst listed only the default option's at-risk order, so O-2205 was not eligible for a notice. If you choose A, a notice for Tall Pines will be needed.", "decision_needed": true})
======================================================================

======================================================================
Orchestrator's result
======================================================================
Ended: The orchestrator called finish.
Tool calls: 4
Decision needed by a person: yes
Summary for a person:
  Marlow can't ship PO-5520 (200 BL-12 boilers) on time and wants a choice of option within 3 business days. If we don't reply, Marlow ships Option B.
- Option A: 80 units on day 7 and 120 on day 21. This puts O-2205 (Tall Pines Coffee House, late penalty) at risk. It would be 5 units short and 4 days late.
- Option B (the default): all 200 units on day 13. This puts O-2203 (Elm State University Dining, late penalty) at risk. It would be 40 units short and 1 day late.
Decision for you: choose A or B and tell Marlow before the deadline. Both at-risk orders carry late penalties.
Drafts saved for your review, none sent:
- Reply to Marlow. It asks about earlier or partial shipments and extra welding capacity, and it doesn't accept either option.
- Notice to Elm State for O-2203. This notice assumes Option B. Send it only if you pick B or let the default apply.
No notice is drafted for O-2205 (Tall Pines). The analyst listed only the default option's at-risk order, so O-2205 was not eligible for a notice. If you choose A, a notice for Tall Pines will be needed.

======================================================================
Summary
======================================================================
Drafts saved (2):
  - supplier reply: week-05\drafts\copperline-coffee\02-marlow-boiler-options__supplier-reply.txt (reviewer APPROVE, 1 revision(s))
  - customer notice O-2203: week-05\drafts\copperline-coffee\02-marlow-boiler-options__customer-O-2203.txt (reviewer APPROVE, 0 revision(s))

Drafts marked for a person (2):
  - supplier reply: Copperline Coffee Machines must make a decision first (see Decisions for a person)
  - customer notice O-2203: order has a late penalty

Decisions for a person (4):
  - Choose Option A or Option B and tell Marlow within three business days. After that Marlow will ship Option B by default. The orders_at_risk list above shows Option B, the default.
  - Option A puts O-2205 (Tall Pines Coffee House, late penalty) at risk. It would be 5 units short on its day-17 ship date and ready on day 21, which is 4 days late.
  - Option B puts O-2203 (Elm State University Dining, late penalty) at risk. It would be 40 units short on its day-12 ship date and ready on day 13, which is 1 day late.
  - Both at-risk orders have late penalties. Weigh a 4-day delay for Tall Pines (Option A) against a 1-day delay for Elm State (Option B).

Tokens by specialist
  specialist         calls     input    output     total
  orchestrator           3     7,299       680     7,979
  analyst                3    10,749     1,307    12,056
  supplier writer        2     3,130     1,691     4,821
  reviewer               3     3,908     4,107     8,015
  customer writer        1       377       182       559
  all                         25,463     7,967    33,430

Saved this output to C:\Users\mikes\OneDrive\Desktop\GBUS-652-Course\GBUS-652-Coursework\week-05\runs\copperline-02-orchestrator.txt
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
