"""MCP server with two Hartwell Foods HR tools: search_policy and get_leave_balance.

Start it (normally Claude Code or an agent starts it for you, over stdio):
    .venv\\Scripts\\python.exe week-04\\hr_mcp_server.py
        HR-staff mode: get_leave_balance takes any employee's work email.
    .venv\\Scripts\\python.exe week-04\\hr_mcp_server.py --as-employee dana.whitfield@hartwellfoods.example
        Employee mode: get_leave_balance takes no inputs and can return only
        that one employee's balance.

Tools:
  search_policy(query)   the 4 closest chunks of the HR documents, with source
                         files. Build or rebuild the database with:
                         .venv\\Scripts\\python.exe week-04\\hr_search.py --rebuild
  get_leave_balance      vacation, sick and personal days left, from
                         hartwell-hr/employees.csv (read fresh on every call).

No API key is needed: the server only looks things up; the client's model
writes the reply.
"""

from __future__ import annotations

import argparse
import csv
import sys
from email.utils import parseaddr
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import hr_search

HERE = Path(__file__).resolve().parent
EMPLOYEES_CSV = HERE / "hartwell-hr" / "employees.csv"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
BALANCE_FIELDS = ("vacation_days_left", "sick_days_left", "personal_days_left")


def normalize_email(value: str) -> str:
    """Accept 'name@x', ' Name@X ' or 'Dana Whitfield <dana@x>'; return lowercase address."""
    return parseaddr(value.strip())[1].strip().lower()


def find_employee(email: str) -> dict | None:
    wanted = normalize_email(email)
    if not wanted:
        return None
    with EMPLOYEES_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["email"].strip().lower() == wanted:
                return row
    return None


def balance_for(email: str) -> dict:
    row = find_employee(email)
    if row is None:
        raise ToolError(
            f"No employee record matches '{email}'. Do NOT state, estimate or guess any "
            "leave balance. Tell the sender their record could not be found and that "
            "a person from HR will follow up.")
    out = {"email": row["email"], "name": row["name"], "department": row["department"],
           "manager": row["manager"] or None}
    for field in BALANCE_FIELDS:
        out[field] = int(row[field])
    return out


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def search_policy(query: str) -> dict:
    """Search the Hartwell Foods HR policy documents (leave and time off, jury duty,
    bereavement, parental and family leave, benefits enrollment, remote work,
    reporting workplace concerns).

    Returns the 4 closest document sections. Each has source_file (cite it),
    document, section, similarity (0 to 1, higher is closer) and text. Base policy
    statements only on the returned text; if no result answers the question, say
    the policies don't cover it.
    """
    try:
        return hr_search.search(query)
    except hr_search.SearchUnavailable as exc:
        raise ToolError(str(exc)) from exc


def get_leave_balance_hr(email: str) -> dict:
    """Look up an employee's remaining leave by their work email address
    (e.g. dana.whitfield@hartwellfoods.example).

    Returns name, department, manager, vacation_days_left, sick_days_left and
    personal_days_left. For HR staff use.
    """
    return balance_for(email)


def make_employee_tool(email: str):
    def get_leave_balance_self() -> dict:
        # Any arguments a client sends are dropped by the SDK, so say plainly whose
        # balance this is, in case the model asked about someone else.
        out = balance_for(email)
        out["note"] = (f"This is the balance of {out['name']} ({out['email']}), the only "
                       "employee this session can see. It is not anyone else's balance.")
        return out

    get_leave_balance_self.__doc__ = (
        f"Get the remaining leave of the employee this session belongs to ({email}). "
        "Takes no inputs and can return only this one employee's balance; it cannot "
        "look up anyone else. Returns name, department, manager, vacation_days_left, "
        "sick_days_left and personal_days_left.")
    return get_leave_balance_self


def build_server(as_employee: str | None) -> MCPServer:
    server = MCPServer(
        name="hartwell-hr",
        instructions=("Hartwell Foods HR tools. Use search_policy for policy questions and "
                      "get_leave_balance for leave balances. Never state a policy or a number "
                      "that didn't come from a tool."))
    server.add_tool(search_policy, name="search_policy", title="Search HR policies",
                    annotations=READ_ONLY)
    if as_employee:
        server.add_tool(make_employee_tool(as_employee), name="get_leave_balance",
                        title="Get my leave balance", annotations=READ_ONLY)
    else:
        server.add_tool(get_leave_balance_hr, name="get_leave_balance",
                        title="Get an employee's leave balance", annotations=READ_ONLY)
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Hartwell Foods HR MCP server (stdio).")
    ap.add_argument("--as-employee", metavar="EMAIL",
                    help="employee mode: get_leave_balance returns only this employee's balance")
    args = ap.parse_args()

    as_employee = None
    if args.as_employee is not None:
        as_employee = normalize_email(args.as_employee)
        if not as_employee:
            sys.exit("--as-employee needs an email address.")
        if find_employee(as_employee) is None:
            print(f"Warning: no record in employees.csv matches {as_employee}; "
                  "get_leave_balance will return an error.", file=sys.stderr)
        print(f"hartwell-hr: employee mode for {as_employee}", file=sys.stderr)
    else:
        print("hartwell-hr: HR-staff mode", file=sys.stderr)

    build_server(as_employee).run("stdio")


if __name__ == "__main__":
    main()
