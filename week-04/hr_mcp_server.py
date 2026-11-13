"""MCP server with two HR tools for one organization: search_policy and get_leave_balance.

Start it (normally Claude Code or an agent starts it for you, over stdio):
    .venv\\Scripts\\python.exe week-04\\hr_mcp_server.py
        HR-staff mode: get_leave_balance takes any employee's work email.
    .venv\\Scripts\\python.exe week-04\\hr_mcp_server.py --as-employee dana.whitfield@hartwellfoods.example
        Employee mode: get_leave_balance takes no inputs and can return only
        that one employee's balance.
    .venv\\Scripts\\python.exe week-04\\hr_mcp_server.py --org ridgeline-hotels --as-employee jenna.morales@ridgelinehotels.example
        The same, for another organization folder (see hr_org.py). Without
        --org, week-04/hartwell-hr is used.

Tools:
  search_policy(query)   the 4 closest chunks of the organization's HR
                         documents, with source files. Build or rebuild an
                         organization's database with:
                         .venv\\Scripts\\python.exe week-04\\hr_search.py [--org ORG] --rebuild
  get_leave_balance      the employee's record from <org>/employees.csv (read
                         fresh on every call). Column names are worked out from
                         the header row and returned as the file names them.

No API key is needed: the server only looks things up; the client's model
writes the reply.
"""

from __future__ import annotations

import argparse
import sys

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import hr_org
import hr_search

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def employee_file(org) -> hr_org.EmployeeFile:
    """Read fresh on every call, so edits to employees.csv show up without a restart."""
    try:
        return hr_org.EmployeeFile(org / "employees.csv")
    except (OSError, hr_org.OrgError) as exc:
        raise ToolError(f"The employee file could not be read: {exc}") from exc


def balance_for(org, email: str) -> dict:
    record = employee_file(org).find(email)
    if record is None:
        raise ToolError(
            f"No employee record matches '{email}'. Do NOT state, estimate or guess any "
            "leave balance. Tell the sender their record could not be found and that "
            "a person from the HR team will follow up.")
    return record


def doc_titles(org) -> list[str]:
    titles = []
    for path in sorted((org / "hr-docs").glob("*.htm*")):
        try:
            titles.append(hr_search.load_html(path)[0] or path.stem)
        except Exception:
            titles.append(path.stem.replace("-", " "))
    return titles


def build_server(org, as_employee: str | None) -> MCPServer:
    name = hr_org.display_name(org)
    columns = hr_org.EmployeeFile(org / "employees.csv")
    fields = ", ".join(columns.columns)
    balances = ", ".join(columns.balance_cols)
    titles = "; ".join(doc_titles(org))
    example = columns.rows[0][columns.email_col] if columns.rows else "name@example.com"

    def search_policy(query: str) -> dict:
        try:
            return hr_search.search(query)
        except hr_search.SearchUnavailable as exc:
            raise ToolError(str(exc)) from exc

    search_policy.__doc__ = (
        f"Search the {name} HR policy documents ({titles}).\n\n"
        "Returns the 4 closest document sections. Each has source_file (cite it), "
        "document, section, similarity (0 to 1, higher is closer) and text. Base policy "
        "statements only on the returned text; if no result answers the question, say "
        "the policies don't cover it.")

    def get_leave_balance_hr(email: str) -> dict:
        return balance_for(org, email)

    get_leave_balance_hr.__doc__ = (
        f"Look up a {name} employee's record by their work email address (e.g. {example}).\n\n"
        f"Returns the employee-file fields {fields}. The leave balances are {balances}. "
        "For HR staff use.")

    def get_leave_balance_self() -> dict:
        # Any arguments a client sends are dropped by the SDK, so say plainly whose
        # balance this is, in case the model asked about someone else.
        file = employee_file(org)
        out = balance_for(org, as_employee)
        out["note"] = (f"This is the record of {file.name_of(out)} ({as_employee}), the only "
                       "employee this session can see. It is not anyone else's balance.")
        return out

    get_leave_balance_self.__doc__ = (
        f"Get the remaining leave of the {name} employee this session belongs to "
        f"({as_employee}). Takes no inputs and can return only this one employee's record; "
        f"it cannot look up anyone else. Returns the employee-file fields {fields}. "
        f"The leave balances are {balances}.")

    server = MCPServer(
        name=org.name,
        instructions=(f"{name} HR tools. Use search_policy for policy questions and "
                      "get_leave_balance for leave balances. Never state a policy or a number "
                      "that didn't come from a tool."))
    server.add_tool(search_policy, name="search_policy", title="Search HR policies",
                    annotations=READ_ONLY)
    if as_employee:
        server.add_tool(get_leave_balance_self, name="get_leave_balance",
                        title="Get my leave balance", annotations=READ_ONLY)
    else:
        server.add_tool(get_leave_balance_hr, name="get_leave_balance",
                        title="Get an employee's leave balance", annotations=READ_ONLY)
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="HR MCP server for one organization (stdio).")
    ap.add_argument("--org", metavar="FOLDER",
                    help="organization folder (default: week-04/hartwell-hr); "
                         "a bare name means a folder inside week-04")
    ap.add_argument("--as-employee", metavar="EMAIL",
                    help="employee mode: get_leave_balance returns only this employee's balance")
    args = ap.parse_args()

    def setup():
        org = hr_org.resolve(args.org)
        columns = hr_org.EmployeeFile(org / "employees.csv")
        return org, columns

    org, columns = hr_org.fail_on_org_error(setup)
    hr_search.use_org(org)
    print(f"{org.name}: employee file read with {columns.describe()}", file=sys.stderr)

    as_employee = None
    if args.as_employee is not None:
        as_employee = hr_org.normalize_email(args.as_employee)
        if not as_employee:
            sys.exit("--as-employee needs an email address.")
        if columns.find(as_employee) is None:
            print(f"Warning: no record in employees.csv matches {as_employee}; "
                  "get_leave_balance will return an error.", file=sys.stderr)
        print(f"{org.name}: employee mode for {as_employee}", file=sys.stderr)
    else:
        print(f"{org.name}: HR-staff mode", file=sys.stderr)

    build_server(org, as_employee).run("stdio")


if __name__ == "__main__":
    main()
