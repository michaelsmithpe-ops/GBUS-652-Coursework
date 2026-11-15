"""Load an organization's sample emails into a Gmail sandbox inbox over IMAP.

Usage (run from the top of the repository):
    .venv\\Scripts\\python.exe week-04\\load_inbox.py             # load the Hartwell sample emails
    .venv\\Scripts\\python.exe week-04\\load_inbox.py --org ridgeline-hotels   # load Ridgeline's instead
    .venv\\Scripts\\python.exe week-04\\load_inbox.py --dry-run   # show what would be loaded; no sign-in

--org takes the same values as agent.py --org (default: week-04/hartwell-hr).
Each .eml file in <org>/sample-emails is placed directly in the
INBOX with IMAP APPEND, as an unread message dated now. Nothing is sent: no
SMTP is used and no message leaves the mailbox. Running it twice loads the
emails twice.

The login is read at run time from Agent-Email.txt in the folder above the
repository. Accepted layouts:
    two lines:           the email address, then the password
    labelled lines:      email: ...   password: ...   (":" or "=", any order;
                         labels like user/username/address/login and
                         password/pass/app_password also work)
Gmail needs an app password here (Google Account > Security > App passwords),
not the normal account password.

The password is never printed, logged or written to any file, and error
messages never repeat the contents of Agent-Email.txt.
"""

from __future__ import annotations

import argparse
import imaplib
import re
import sys
import time
from email.utils import formatdate, make_msgid
from pathlib import Path

HERE = Path(__file__).resolve().parent                  # .../GBUS-652-Coursework/week-04
DEFAULT_ORG_DIR = HERE / "hartwell-hr"
LOGIN_FILE = HERE.parents[1] / "Agent-Email.txt"         # folder that contains the repo
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
MAILBOX = "INBOX"

ADDRESS_KEYS = {"email", "e-mail", "address", "email address", "user", "username", "login", "account"}
PASSWORD_KEYS = {"password", "pass", "passwd", "app password", "app_password", "app-password", "apppassword"}


class LoginFileError(Exception):
    """Agent-Email.txt is missing or not in a layout we understand. Never includes its contents."""


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 _-]*?)\s*[:=]\s*(.*)$")
# Characters that copy-and-paste can slip in invisibly: non-breaking and zero-width spaces, BOMs.
INVISIBLE = "   ​‌‍⁠﻿"


def _parse_login_text(text: str) -> tuple[str | None, str | None, str]:
    """Return (address, password, layout description). Never raises; never logs."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip(" \t" + INVISIBLE)]
    address = password = None
    layout = "unrecognized"

    # Labelled lines: "email: x" / "password = y" (any label containing "pass" is the password)
    for ln in lines:
        m = LABEL_RE.match(ln)
        if not m:
            continue
        key, value = m.group(1).strip().lower(), m.group(2).strip().strip('"').strip("'")
        if "pass" in key and value:
            password, layout = value, "labelled lines"
        elif key in ADDRESS_KEYS or any(w in key for w in ("mail", "user", "login", "account", "address")):
            found = EMAIL_RE.search(value)
            if found:
                address = found.group(0)

    # Unlabelled: the address is whichever line holds an email address; the password is the other line.
    if address is None:
        for ln in lines:
            found = EMAIL_RE.search(ln)
            if found:
                address = found.group(0)
                break
    if password is None:
        others = [ln for ln in lines if not EMAIL_RE.search(ln)]
        if len(others) == 1:
            password = others[0].strip('"').strip("'")
            layout = "two plain lines" if len(lines) == 2 else "address line plus one other line"

    if password is not None:
        # Google shows app passwords as four groups of four letters. Drop any spaces between
        # them, including invisible ones picked up when copying from the Google page.
        squeezed = re.sub(r"[\s" + INVISIBLE + "]", "", password)
        if re.fullmatch(r"[A-Za-z]{16}", squeezed):
            password = squeezed
    return address, password, layout


def read_login() -> tuple[str, str]:
    try:
        text = LOGIN_FILE.read_text(encoding="utf-8-sig")
    except OSError:
        raise LoginFileError(f"Could not read {LOGIN_FILE}.") from None
    address, password, _ = _parse_login_text(text)
    if not address or not password:
        raise LoginFileError(
            f"Could not find an email address and password in {LOGIN_FILE.name}. "
            "Use two lines (address, then password) or labelled lines "
            "(email: ... and password: ...). Run with --check for details.")
    return address, password


def check_login_file() -> None:
    """Report pass/fail facts about Agent-Email.txt without showing the address or password."""
    print(f"Checking {LOGIN_FILE} (contents are not shown)\n")
    if not LOGIN_FILE.exists():
        print("  FAIL  The file does not exist at that path.")
        near = [p.name for p in LOGIN_FILE.parent.glob("Agent*Email*")]
        if near:
            print("        Similar names in that folder: " + ", ".join(near))
        return
    raw = LOGIN_FILE.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        encoding_ok = True
    except UnicodeDecodeError:
        text, encoding_ok = raw.decode("utf-8", "replace"), False
    address, password, layout = _parse_login_text(text)
    nonblank = [ln for ln in text.splitlines() if ln.strip()]

    def row(ok: bool, msg: str) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'}  {msg}")

    row(encoding_ok, "File is readable text (UTF-8)" if encoding_ok else
        "File is not UTF-8 text; re-save it in Notepad as UTF-8")
    row(True, f"Non-blank lines: {len(nonblank)}; layout understood as: {layout}")
    row(address is not None, "Found an email address" if address else "No email address found")
    if address:
        domain = address.split("@")[-1].lower()
        row(domain in ("gmail.com", "googlemail.com"),
            "Address is a gmail.com address" if domain in ("gmail.com", "googlemail.com") else
            "Address is not @gmail.com (fine only for Google Workspace accounts, whose admins may block app passwords)")
    row(password is not None, "Found a password line" if password else "No password found")
    if password:
        app_like = re.fullmatch(r"[A-Za-z]{16}", password) is not None
        row(app_like, "Password looks like a Google app password (16 letters)" if app_like else
            "Password does NOT look like a Google app password (16 letters, spaces optional); "
            "it may be the normal account password, or have a typo or extra characters")
        if app_like and not password.islower():
            row(False, "Password has capital letters; Google app passwords are all lowercase")
        bad = [c for c in password if c in INVISIBLE or ord(c) < 32]
        row(not bad, "No invisible characters in the password" if not bad else
            "Password contains invisible characters (from copy and paste); retype it")
    print("\nNothing was sent and no sign-in was attempted.")


def login_error_text(exc: Exception, address: str) -> str:
    """Gmail's reason for refusing a sign-in. It never contains the password; hide the address anyway."""
    text = exc.args[0] if exc.args else str(exc)
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return re.sub(re.escape(address), "[sandbox account]", str(text), flags=re.IGNORECASE)


def build_message(path: Path, msgid_domain: str = "hartwellfoods.example") -> bytes:
    """Add today's Date and a fresh Message-ID; use CRLF line endings as IMAP expects."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    header_end = raw.find(b"\n\n")
    headers, body = (raw, b"") if header_end == -1 else (raw[:header_end], raw[header_end:])
    kept = [h for h in headers.split(b"\n")
            if not re.match(rb"(?i)^(date|message-id):", h)]
    new_headers = [f"Date: {formatdate(localtime=True)}".encode(),
                   f"Message-ID: {make_msgid(domain=msgid_domain)}".encode()]
    return (b"\n".join(new_headers + kept) + body).replace(b"\n", b"\r\n")


def subject_of(message: bytes) -> str:
    m = re.search(rb"(?im)^Subject:\s*(.*)$", message)
    return m.group(1).decode("utf-8", "replace").strip() if m else "(no subject)"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Place the sample emails in the Gmail sandbox inbox (nothing is sent).")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be loaded without signing in or reading Agent-Email.txt")
    ap.add_argument("--check", action="store_true",
                    help="check Agent-Email.txt's layout without showing its contents or signing in")
    ap.add_argument("--org", metavar="FOLDER",
                    help="organization folder whose sample-emails to load (default: week-04/hartwell-hr); "
                         "a bare name means a folder inside week-04")
    args = ap.parse_args()

    if args.check:
        check_login_file()
        return

    if args.org:
        given = Path(args.org).expanduser()
        org_dir = (given if given.is_dir() else HERE / args.org).resolve()
    else:
        org_dir = DEFAULT_ORG_DIR
    emails_dir = org_dir / "sample-emails"
    if not emails_dir.is_dir():
        sys.exit(f"No sample-emails folder found in {org_dir}")
    files = sorted(emails_dir.glob("*.eml"))
    if not files:
        sys.exit(f"No .eml files found in {emails_dir}")
    domain = "hartwellfoods.example" if org_dir == DEFAULT_ORG_DIR else f"{org_dir.name}.example"
    messages = [(f, build_message(f, domain)) for f in files]
    print(f"Organization: {org_dir.name}")

    if args.dry_run:
        print(f"Dry run: {len(messages)} emails would be placed in {MAILBOX} as unread, dated now:")
        for f, msg in messages:
            print(f"  {f.name:28s} {subject_of(msg)}  ({len(msg)} bytes)")
        return

    try:
        address, password = read_login()
    except LoginFileError as exc:
        sys.exit(str(exc))

    print(f"Signing in to {IMAP_HOST} ...")
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    except OSError as exc:
        sys.exit(f"Could not connect to {IMAP_HOST}: {exc}")
    try:
        try:
            imap.login(address, password)
        except imaplib.IMAP4.error as exc:
            sys.exit("Sign-in failed. Gmail said: " + login_error_text(exc, address) + "\n"
                     "Check the address and app password in Agent-Email.txt "
                     "(Gmail needs an app password, not the account password).")
        finally:
            del password
        print("Signed in.\n")

        now = time.time()
        loaded = 0
        for f, msg in messages:
            # No flags, so the message arrives unread (no \Seen). The internal date is now.
            status, data = imap.append(MAILBOX, None, imaplib.Time2Internaldate(now), msg)
            if status == "OK":
                loaded += 1
                print(f"  placed  {f.name:28s} {subject_of(msg)}")
            else:
                detail = data[0].decode("utf-8", "replace") if data and data[0] else status
                print(f"  FAILED  {f.name:28s} {detail}")
        print(f"\n{loaded} of {len(messages)} emails placed in {MAILBOX} as unread. Nothing was sent.")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
