"""MCP server with Brookfield Bicycle Company's supply data tools.

Start it (normally Claude Code or an agent starts it for you, over stdio), from the
top of the repository:
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py

It reads the five CSV files in week-05/brookfield-bikes, fresh on every call, so
edits show up without a restart:
    parts.csv              part_id, description, on_hand, supplier
    bill-of-materials.csv  model, part_id, qty_per_bike
    inbound.csv            po_number, part_id, supplier, qty, arrives_in_days
    orders.csv             order_id, customer, contact_email, model, qty, ship_in_days, late_penalty
    suppliers.csv          supplier, contact_name, contact_email, part_id

Tools (all read-only; days are counted from today, which is day 0):
  get_part(part_id)               stock on hand, scheduled shipments, and the models
                                  that use the part
  get_orders_for_part(part_id)    open orders that need the part, in ship-day order,
                                  with units needed (bikes x parts per bike)
  check_coverage(part_id, arrivals)
                                  replaces the part's scheduled shipments with a new
                                  list of arrivals and fills orders complete, in
                                  ship-day order: an order ships only when all of its
                                  units are there, and orders after it wait for it.
                                  For each order: covered, or units short and the
                                  first day it can ship.

No API key is needed: the server only looks things up and does arithmetic.
The functions can also be imported by other week-05 programs.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent                  # .../GBUS-652-Coursework/week-05
DATA_DIR = HERE / "brookfield-bikes"

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


# ---------------------------------------------------------------------------
# Reading the CSV files
# ---------------------------------------------------------------------------

def read_csv(name: str) -> list[dict]:
    """Read one CSV file as a list of dicts, with spaces trimmed from every value."""
    path = DATA_DIR / name
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [{k.strip(): (v or "").strip() for k, v in row.items() if k}
                    for row in csv.DictReader(f)]
    except OSError as exc:
        raise ToolError(f"Could not read {name}: {exc}") from exc


def to_int(value: str, what: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ToolError(f"{what} is not a whole number: {value!r}") from exc


def normalize_part(part_id: str) -> str:
    return (part_id or "").strip().upper()


def find_part(part_id: str) -> dict:
    """Return the parts.csv row for part_id, or raise a ToolError naming the known parts."""
    wanted = normalize_part(part_id)
    parts = read_csv("parts.csv")
    for row in parts:
        if row["part_id"].upper() == wanted:
            return row
    known = ", ".join(r["part_id"] for r in parts)
    raise ToolError(f"No part '{part_id}' in parts.csv. Known parts: {known}.")


def models_using(part_id: str) -> dict[str, int]:
    """{model: parts per bike} for every model whose bill of materials includes the part."""
    return {row["model"]: to_int(row["qty_per_bike"], f"qty_per_bike for {row['model']}")
            for row in read_csv("bill-of-materials.csv")
            if row["part_id"].upper() == part_id}


def scheduled_shipments(part_id: str) -> list[dict]:
    rows = [r for r in read_csv("inbound.csv") if r["part_id"].upper() == part_id]
    shipments = [{"po_number": r["po_number"], "supplier": r["supplier"],
                  "qty": to_int(r["qty"], f"qty on {r['po_number']}"),
                  "arrives_in_days": to_int(r["arrives_in_days"], f"arrives_in_days on {r['po_number']}")}
                 for r in rows]
    return sorted(shipments, key=lambda s: (s["arrives_in_days"], s["po_number"]))


def orders_needing(part_id: str) -> list[dict]:
    """Open orders whose model uses the part, sorted by ship day (then order_id)."""
    per_bike = models_using(part_id)
    orders = []
    for r in read_csv("orders.csv"):
        if r["model"] not in per_bike:
            continue
        bikes = to_int(r["qty"], f"qty on {r['order_id']}")
        orders.append({
            "order_id": r["order_id"],
            "customer": r["customer"],
            "model": r["model"],
            "bikes": bikes,
            "parts_per_bike": per_bike[r["model"]],
            "units_needed": bikes * per_bike[r["model"]],
            "ship_day": to_int(r["ship_in_days"], f"ship_in_days on {r['order_id']}"),
            "late_penalty": r["late_penalty"].lower() == "yes",
        })
    return sorted(orders, key=lambda o: (o["ship_day"], o["order_id"]))


# ---------------------------------------------------------------------------
# The three tools
# ---------------------------------------------------------------------------

def get_part(part_id: str) -> dict:
    """Look up one part: its stock on hand, its scheduled shipments, and the models that use it.

    part_id is the part number, such as MC-500. Days are counted from today (day 0).
    Returns part_id, description, supplier, on_hand (units in stock today),
    scheduled_shipments (po_number, supplier, qty, arrives_in_days, earliest first),
    total_scheduled, and used_in_models (model and parts_per_bike).
    """
    row = find_part(part_id)
    pid = row["part_id"].upper()
    shipments = scheduled_shipments(pid)
    return {
        "part_id": row["part_id"],
        "description": row["description"],
        "supplier": row["supplier"],
        "on_hand": to_int(row["on_hand"], f"on_hand for {pid}"),
        "scheduled_shipments": shipments,
        "total_scheduled": sum(s["qty"] for s in shipments),
        "used_in_models": [{"model": m, "parts_per_bike": n} for m, n in models_using(pid).items()],
    }


def get_orders_for_part(part_id: str) -> dict:
    """List the open customer orders that need a part, earliest ship day first.

    part_id is the part number, such as MC-500. Days are counted from today (day 0).
    For each order: order_id, customer, model, bikes, parts_per_bike, units_needed
    (bikes x parts per bike), ship_day, and late_penalty (true if the contract has a
    penalty for shipping late). Also returns total_units_needed.
    """
    pid = find_part(part_id)["part_id"].upper()
    orders = orders_needing(pid)
    return {"part_id": pid, "orders": orders,
            "total_units_needed": sum(o["units_needed"] for o in orders)}


class Arrival(BaseModel):
    """One delivery of the part."""
    qty: int = Field(description="Number of units in this delivery (a whole number above 0).")
    arrives_in_days: int = Field(description="Day it arrives, counted from today (day 0).")


def check_coverage(part_id: str, arrivals: list[Arrival]) -> dict:
    """Check which open orders a new delivery schedule for a part can cover.

    part_id is the part number, such as MC-500. arrivals is the NEW list of deliveries
    (qty and arrives_in_days, counted from today = day 0). It REPLACES all of the part's
    scheduled shipments; stock on hand counts as available on day 0. To check the
    current schedule, pass the shipments from get_part.

    Orders are filled complete, in ship-day order: an order ships only when all of its
    units are available, and every order after it waits for it, so a short order holds
    up the ones behind it.

    For each order: order_id, customer, model, units_needed, ship_day, late_penalty,
    status ("covered" or "short"), and for a short order units_short (units missing on
    its ship day), ready_day (first day it can ship; null if these arrivals never cover
    it) and days_late. Also returns a summary with orders_at_risk.
    """
    part = find_part(part_id)
    pid = part["part_id"].upper()
    on_hand = to_int(part["on_hand"], f"on_hand for {pid}")

    schedule = []
    for i, a in enumerate(arrivals, start=1):
        if a.qty <= 0:
            raise ToolError(f"Arrival {i}: qty must be above 0 (got {a.qty}).")
        if a.arrives_in_days < 0:
            raise ToolError(f"Arrival {i}: arrives_in_days can't be before today (got {a.arrives_in_days}).")
        schedule.append({"qty": a.qty, "arrives_in_days": a.arrives_in_days})
    schedule.sort(key=lambda a: a["arrives_in_days"])

    # Supply available by each day: stock on hand at day 0, then each arrival.
    steps = [(0, on_hand)]
    for a in schedule:
        steps.append((a["arrives_in_days"], steps[-1][1] + a["qty"]))

    def supply_by(day: int) -> int:
        return max(total for d, total in steps if d <= day)

    def first_day_with(units: int) -> int | None:
        return next((d for d, total in steps if total >= units), None)

    # An order can ship once supply covers it AND every order ahead of it, so ready days
    # never go backwards: a short order holds up the ones behind it.
    results, needed_so_far = [], 0
    for o in orders_needing(pid):
        needed_so_far += o["units_needed"]          # this order plus every order ahead of it
        ready = first_day_with(needed_so_far)
        entry = {k: o[k] for k in ("order_id", "customer", "model", "units_needed",
                                   "ship_day", "late_penalty")}
        if ready is not None and ready <= o["ship_day"]:
            entry["status"] = "covered"
        else:
            missing = needed_so_far - supply_by(o["ship_day"])
            entry.update({
                "status": "short",
                "units_short": min(o["units_needed"], missing),
                "ready_day": ready,
                "days_late": None if ready is None else ready - o["ship_day"],
            })
            if ready is None:
                entry["note"] = "These arrivals never cover this order."
        results.append(entry)

    short = [r for r in results if r["status"] == "short"]
    total_needed = needed_so_far
    total_supply = steps[-1][1]
    return {
        "part_id": pid,
        "on_hand": on_hand,
        "arrivals_used": schedule,
        "orders": results,
        "summary": {
            "orders_checked": len(results),
            "orders_covered": len(results) - len(short),
            "orders_at_risk": [r["order_id"] for r in short],
            "orders_at_risk_with_late_penalty": [r["order_id"] for r in short if r["late_penalty"]],
            "total_units_needed": total_needed,
            "total_supply": total_supply,
            "units_left_over": max(0, total_supply - total_needed),
        },
    }


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def build_server() -> MCPServer:
    server = MCPServer(
        name="brookfield-supply",
        instructions=("Brookfield Bicycle Company's planning data: parts, scheduled shipments "
                      "and open customer orders. Days are counted from today (day 0). Use "
                      "check_coverage for any question about which orders a delivery schedule "
                      "covers; never work out coverage yourself."))
    server.add_tool(get_part, name="get_part", title="Get a part", annotations=READ_ONLY)
    server.add_tool(get_orders_for_part, name="get_orders_for_part",
                    title="Get open orders for a part", annotations=READ_ONLY)
    server.add_tool(check_coverage, name="check_coverage",
                    title="Check order coverage for a delivery schedule", annotations=READ_ONLY)
    return server


def main() -> None:
    parts = read_csv("parts.csv")
    print(f"brookfield-supply: reading {DATA_DIR} ({len(parts)} parts)", file=sys.stderr)
    build_server().run("stdio")


if __name__ == "__main__":
    main()
