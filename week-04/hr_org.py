"""Organization folders for the week-04 HR agent.

An organization folder is laid out like week-04/hartwell-hr:
    hr-docs/            the policy documents (HTML)
    employees.csv       one row per employee
    system_prompt.txt   the agent's system prompt
    sample-emails/      example .eml files (not needed to run the agent)

--org accepts a folder path (week-04/ridgeline-hotels) or just a folder name
inside week-04 (ridgeline-hotels). Without --org, week-04/hartwell-hr is used.

Each organization gets its own Chroma database (all git-ignored):
    hartwell-hr  -> week-04/chroma_db              (as before)
    any other    -> week-04/chroma_db-<folder name>

The employee file's column names are not assumed. They are worked out from the
header row (see EmployeeFile).
"""

from __future__ import annotations

import csv
import re
import sys
from email.utils import parseaddr
from pathlib import Path

HERE = Path(__file__).resolve().parent              # .../GBUS-652-Coursework/week-04
DEFAULT_ORG = HERE / "hartwell-hr"
REQUIRED = ("hr-docs", "employees.csv", "system_prompt.txt")


class OrgError(Exception):
    """The organization folder is missing or not laid out as expected."""


def resolve(value: str | None) -> Path:
    """Turn an --org value into an organization folder, checking its layout."""
    if not value:
        path = DEFAULT_ORG
    else:
        given = Path(value).expanduser()
        path = given if given.is_dir() else HERE / value
    path = path.resolve()
    if not path.is_dir():
        raise OrgError(f"Organization folder not found: {value}")
    missing = [name for name in REQUIRED if not (path / name).exists()]
    if missing:
        nested = [p.name for p in path.iterdir() if p.is_dir() and (p / "employees.csv").exists()]
        hint = f" It holds another folder ({nested[0]}) that may be the real one." if nested else ""
        raise OrgError(f"{path} is missing {', '.join(missing)}.{hint}")
    return path


def db_dir(org: Path) -> Path:
    """Where this organization's Chroma database lives."""
    return HERE / "chroma_db" if org == DEFAULT_ORG.resolve() else HERE / f"chroma_db-{org.name}"


def display_name(org: Path) -> str:
    """The organization's name, from 'You are the HR assistant for X.' in its system prompt."""
    try:
        text = (org / "system_prompt.txt").read_text(encoding="utf-8")
    except OSError:
        text = ""
    m = re.search(r"assistant for ([^.\n]+)\.", text)
    return m.group(1).strip() if m else org.name.replace("-", " ").title()


def normalize_email(value: str) -> str:
    """Accept 'name@x', ' Name@X ' or 'Dana Whitfield <dana@x>'; return lowercase address."""
    return parseaddr(value.strip())[1].strip().lower()


# ---------------------------------------------------------------------------
# Employee file
# ---------------------------------------------------------------------------

BALANCE_WORDS = re.compile(r"(?i)\b(left|remaining|balance|available|accrued|days|hours)\b")


def _key(header: str) -> str:
    """'PTO Days Remaining' -> 'pto days remaining'; 'vacation_days_left' -> 'vacation days left'."""
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def _is_int(value: str) -> bool:
    return re.fullmatch(r"-?\d+", value.strip()) is not None


class EmployeeFile:
    """employees.csv, with its columns worked out from the header row and the data:

    - email column:    the header that mentions "email" (or, failing that, the
                       column whose every value is an email address)
    - name column:     the header that mentions "name"
    - balance columns: headers that mention left / remaining / balance / available
                       / days / hours AND whose every value is a whole number
    - other columns:   returned as they are (e.g. department, hotel, supervisor)

    Records keep the file's own column names, so the agent sees "PTO Days
    Remaining" at Ridgeline and "vacation_days_left" at Hartwell.
    """

    def __init__(self, path: Path):
        self.path = path
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            self.columns = [c for c in (reader.fieldnames or []) if c is not None]
            self.rows = [{c: (row.get(c) or "").strip() for c in self.columns} for row in reader]
        if not self.columns:
            raise OrgError(f"{path} has no header row.")

        def values(col: str) -> list[str]:
            return [r[col] for r in self.rows if r[col]]

        email_cols = [c for c in self.columns if "email" in _key(c)]
        if not email_cols:
            email_cols = [c for c in self.columns
                          if values(c) and all("@" in v for v in values(c))]
        if not email_cols:
            raise OrgError(f"Could not find an email address column in {path} "
                           f"(columns: {', '.join(self.columns)}).")
        self.email_col = email_cols[0]

        names = [c for c in self.columns if c != self.email_col and "name" in _key(c).split()]
        self.name_col = names[0] if names else None

        self.balance_cols = [c for c in self.columns
                             if c not in (self.email_col, self.name_col)
                             and BALANCE_WORDS.search(_key(c))
                             and values(c) and all(_is_int(v) for v in values(c))]
        if not self.balance_cols:
            raise OrgError(f"Could not find any leave balance columns in {path} "
                           f"(columns: {', '.join(self.columns)}).")

    def find(self, email: str) -> dict | None:
        """The record for this email address, or None. Balances are numbers; blanks are None."""
        wanted = normalize_email(email)
        if not wanted:
            return None
        for row in self.rows:
            if row[self.email_col].lower() == wanted:
                return {c: (int(row[c]) if c in self.balance_cols and row[c]
                            else (row[c] or None)) for c in self.columns}
        return None

    def name_of(self, record: dict) -> str:
        return (record.get(self.name_col) if self.name_col else None) or record[self.email_col]

    def names_by_email(self) -> dict[str, str]:
        return {r[self.email_col].lower(): (r[self.name_col] if self.name_col else r[self.email_col])
                for r in self.rows if r[self.email_col]}

    def describe(self) -> str:
        """How the columns were read, for messages and tool descriptions."""
        return (f"email column '{self.email_col}', name column '{self.name_col}', "
                f"balance columns {', '.join(repr(c) for c in self.balance_cols)}")


def fail_on_org_error(func):
    """Run func(); turn an OrgError into a clean exit message instead of a traceback."""
    try:
        return func()
    except OrgError as exc:
        sys.exit(f"Error: {exc}")
