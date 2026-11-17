"""Fixed-order coordinator for a company's supplier emails (Brookfield Bicycle by default).

Runs the shared specialists in specialists.py, always in this order:
  1. The supply analyst reads the email and returns its brief.
  2. A customer notice for each order at risk (skipped if there are none).
  3. A reply to the supplier.
Every draft goes through the review step (writer -> reviewer, up to 2 revisions, then the
code name check) and is saved in week-05/drafts/<company folder>. Nothing is sent.

At the end it prints a summary: drafts saved, drafts marked for a person, decisions for a
person, and total tokens.

Run from the top of the repository:
    .venv\\Scripts\\python.exe week-05\\pipeline.py --email week-05\\brookfield-bikes\\supplier-emails\\01-northgate-controller-delay.eml
    .venv\\Scripts\\python.exe week-05\\pipeline.py --email <file> --save week-05\\runs\\pipeline-01.txt

    .venv\\Scripts\\python.exe week-05\\pipeline.py --org copperline-coffee --email week-05\\copperline-coffee\\supplier-emails\\01-danforth-pump-delay.eml

--save FILE also writes everything printed to FILE (UTF-8).
--org FOLDER picks the company: its folder in week-05 (default brookfield-bikes). Drafts
are saved in week-05/drafts/FOLDER. After each review step the final draft is printed
between FINAL DRAFT TO ... and "Marked for a person: yes/no".
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import anthropic

import specialists as s


class Output:
    """Replaces sys.stdout: prints to the console and, with --save, to a file as well."""

    def __init__(self, console):
        self.console = console
        self.file = None

    def write(self, text: str) -> int:
        self.console.write(text)
        if self.file:
            self.file.write(text)
        return len(text)

    def flush(self) -> None:
        self.console.flush()
        if self.file:
            self.file.flush()


def fail(message: str) -> None:
    print(f"Error: {message}")
    sys.exit(1)


def open_save_file(name: str, email_path: Path):
    path = Path(name).expanduser().resolve()
    protected = {s.KEY_FILE.resolve(), (s.KEY_FILE.parent / "Agent-Email.txt").resolve(),
                 (s.KEY_FILE.parent / "Agent-Allowlist.txt").resolve(), email_path}
    if path in protected or path.suffix.lower() in {".py", ".eml", ".csv"}:
        fail(f"--save will not overwrite {path.name}; choose a new .txt file name.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return open(path, "w", encoding="utf-8"), path
    except OSError as exc:
        fail(f"Could not open {name} for writing: {exc.strerror}")


def section(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def run(email_path: Path) -> None:
    email = s.read_email(email_path)
    name = email_path.stem
    print(f"{s.COMPANY} pipeline - {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print(f"Org:    {s.ORG} (drafts in {s.DRAFTS_DIR.relative_to(s.HERE.parent)})")
    print("Columns found:")
    print_columns()
    print(f"Email:  {email_path.name}")
    print(f"Model:  {s.MODEL}")
    print("Order:  1. supply analyst  2. customer notices  3. supplier reply")

    drafts: list[dict] = []
    brief: dict | None = None
    stopped = ""
    try:
        section("Step 1 of 3: supply analyst")
        brief = s.run_analyst(email, sender="pipeline")

        section("Step 2 of 3: customer notices")
        at_risk = brief.get("orders_at_risk", [])
        if not at_risk:
            print("No orders at risk; skipping customer notices.")
        for i, order in enumerate(at_risk, start=1):
            print(f"\n--- Customer notice {i} of {len(at_risk)}: {order.get('order_id')}")
            drafts.append({"kind": f"customer notice {order.get('order_id')}",
                           **s.draft_customer_notice(order, name)})

        section("Step 3 of 3: supplier reply")
        drafts.append({"kind": "supplier reply", **s.draft_supplier_reply(email, brief, name)})
    except STOP_ERRORS as exc:
        stopped = stop_message(exc)

    print_summary(drafts, brief, stopped)


# Errors that stop a run early (the summary still prints).
STOP_ERRORS = (anthropic.APIError, RuntimeError)


def stop_message(exc: Exception) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "The API key in API-Key.txt was rejected."
    if isinstance(exc, anthropic.RateLimitError):
        return "Rate limited by the API; try again in a minute."
    if isinstance(exc, anthropic.APIStatusError):
        return f"API error {exc.status_code}: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the Anthropic API (network error)."
    return str(exc)                                 # refusal, token limit, or a bad brief


def print_summary(drafts: list[dict], brief: dict | None, stopped: str) -> None:
    """The end-of-run summary (shared with orchestrator.py). Exits 1 if the run stopped early."""
    section("Summary")
    if stopped:
        print(f"STOPPED EARLY: {stopped}\n")

    print(f"Drafts saved ({len(drafts)}):")
    for d in drafts:
        print(f"  - {d['kind']}: {Path(d['path']).relative_to(s.HERE.parent)} "
              f"(reviewer {d['verdict']}, {d['revisions']} revision(s))")
    if not drafts:
        print("  (none)")

    flagged = [d for d in drafts if d["needs_person"]]
    print(f"\nDrafts marked for a person ({len(flagged)}):")
    for d in flagged:
        print(f"  - {d['kind']}: {'; '.join(d['reasons'])}")
    if not flagged:
        print("  (none)")

    decisions = (brief or {}).get("decisions_for_a_person", [])
    print(f"\nDecisions for a person ({len(decisions)}):")
    for item in decisions:
        print(f"  - {item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)}")
    if not decisions:
        print("  (none)")

    s.print_token_summary()
    if stopped:
        sys.exit(1)


def main() -> None:
    cli("Run a company's specialists in a fixed order on one supplier email. Sends nothing.",
        run)


def print_columns() -> None:
    """The columns detected in this company's CSV files (no names are assumed)."""
    for name, found in s.sd.detect_columns().items():
        print(f"        {name}: " + ", ".join(f"{k} = {v}" for k, v in found.items()))


def cli(description: str, run_fn) -> None:
    """--email / --save / --org handling, shared with orchestrator.py."""
    out = Output(sys.stdout)
    out.console.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout = out

    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--email", required=True, metavar="FILE", help="path of one supplier email (.eml)")
    ap.add_argument("--save", metavar="FILE", help="also write everything printed to this UTF-8 text file")
    ap.add_argument("--org", default=s.sd.DEFAULT_ORG, choices=s.sd.list_orgs(),
                    help=f"company folder in week-05 (default {s.sd.DEFAULT_ORG})")
    args = ap.parse_args()
    s.set_org(args.org)

    email_path = Path(args.email).expanduser().resolve()
    if not email_path.is_file():
        fail(f"Email file not found: {args.email}")

    save_path = None
    if args.save:
        out.file, save_path = open_save_file(args.save, email_path)
    try:
        run_fn(email_path)
    finally:
        if out.file:
            print(f"\nSaved this output to {save_path}")
            out.file.close()
            out.file = None


if __name__ == "__main__":
    main()
