"""HR email agent: prepares draft replies to employee emails using Claude's tool use.

Usage (run from the top of the repository):
    .venv\\Scripts\\python.exe week-04\\agent.py --email week-04\\hartwell-hr\\sample-emails\\01-dana-vacation.eml
    .venv\\Scripts\\python.exe week-04\\agent.py --inbox
    .venv\\Scripts\\python.exe week-04\\agent.py --inbox --save run-log.txt

Modes:
  --email FILE  Handle one .eml file. save_reply writes a draft to week-04/drafts/.
  --inbox       Sign in to the Gmail sandbox with IMAP (login from Agent-Email.txt
                in the folder above the repository) and handle each unread inbox
                email as its own separate agent run. Each email is marked as read
                BEFORE it is worked on, so no email is handled twice (an email
                whose run fails stays read). save_reply creates a real Gmail draft
                replying to the sender in the same thread; if needs_human_review is
                true, the subject starts with [NEEDS HR REVIEW] and the draft is
                starred (in Gmail, search: in:drafts is:starred).
  --save FILE   Also write everything printed to FILE (UTF-8), relative to the
                current folder.

This program only reads email and creates drafts. It has no way to send email.

How each agent run works:
  1. The sender's address comes from the email's From line.
  2. week-04/hr_mcp_server.py is started with --as-employee <sender>, so
     get_leave_balance can only return the sender's own balance.
  3. Claude gets that server's tools (search_policy, get_leave_balance) plus
     save_reply, and the system prompt from hartwell-hr/system_prompt.txt
     (read fresh on every run).
  4. Each tool call is printed with its inputs and the first 300 characters of
     its result. The run stops when the draft is saved, after 10 tool calls, or
     on any reply that isn't a tool request, and says why. Then the draft and
     the input and output tokens are printed.

Secrets: the Anthropic API key (API-Key.txt) and the Gmail login
(Agent-Email.txt) are read at run time only. The password and API key are
never printed or written to any file, and the sandbox account's address is
replaced with [sandbox account] in everything printed or saved.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import email.policy
import imaplib
import json
import re
import sys
import time
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path

import anthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import load_inbox  # shared Gmail login reader (read_login) and IMAP settings

HERE = Path(__file__).resolve().parent                  # .../GBUS-652-Coursework/week-04
SERVER = HERE / "hr_mcp_server.py"
SYSTEM_PROMPT_FILE = HERE / "hartwell-hr" / "system_prompt.txt"
DRAFTS_DIR = HERE / "drafts"
KEY_FILE = HERE.parents[1] / "API-Key.txt"              # folder that contains the repo
SERVER_LOG = HERE / ".mcp-server.log"                   # git-ignored (*.log)

MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000
MAX_TOOL_CALLS = 10
PREVIEW_CHARS = 300
REVIEW_TAG = "[NEEDS HR REVIEW]"

SAVE_REPLY_TOOL = {
    "name": "save_reply",
    "description": (
        "Save your finished reply to the employee as a draft for the HR team to review. "
        "This only saves a draft; it never sends anything. Call it exactly once, at the end."),
    "input_schema": {
        "type": "object",
        "properties": {
            "reply_text": {
                "type": "string",
                "description": "The full text of the reply email to the employee.",
            },
            "needs_human_review": {
                "type": "boolean",
                "description": "true if a person from HR must handle or check this before anything is sent.",
            },
        },
        "required": ["reply_text", "needs_human_review"],
        "additionalProperties": False,
    },
    "strict": True,
}


# ---------------------------------------------------------------------------
# Output: printed text goes to the console and, with --save, to a file.
# ---------------------------------------------------------------------------

class Output:
    """Replaces sys.stdout. Copies text to an optional log file and hides the sandbox address."""

    def __init__(self, console):
        self.console = console
        self.file = None
        self.redactions: list[tuple[str, str]] = []

    def hide(self, text: str, replacement: str) -> None:
        if text:
            self.redactions.append((text, replacement))

    def write(self, s: str) -> int:
        for secret, replacement in self.redactions:
            s = re.sub(re.escape(secret), replacement, s, flags=re.IGNORECASE)
        self.console.write(s)
        if self.file:
            self.file.write(s)
        return len(s)

    def flush(self) -> None:
        self.console.flush()
        if self.file:
            self.file.flush()


OUT = Output(sys.stdout)


def fail(message: str) -> None:
    print(f"Error: {message}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def load_api_key() -> str:
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        fail(f"Could not read the API key file: {KEY_FILE}")
    if not key:
        fail(f"The API key file is empty: {KEY_FILE}")
    return key


def parse_email(raw: bytes) -> dict | None:
    """Return the parts of an email the agent needs, or None if it has no sender address."""
    msg = BytesParser(policy=email.policy.default).parsebytes(raw)
    name, address = parseaddr(str(msg.get("From", "")))
    address = address.strip().lower()
    if "@" not in address:
        return None
    part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        try:
            body = part.get_content()
        except Exception:
            body = part.get_payload(decode=True).decode("utf-8", "replace") if part.get_payload(decode=True) else ""
        if part.get_content_type() == "text/html":
            from bs4 import BeautifulSoup
            body = BeautifulSoup(body, "html.parser").get_text("\n")
    return {"from_name": name, "from_address": address,
            "subject": str(msg.get("Subject", "")).strip(),
            "message_id": str(msg.get("Message-ID", "")).strip(),
            "references": str(msg.get("References", "")).strip(),
            "body": body.strip()}


def first_message(em: dict) -> str:
    # The email goes inside tags so Claude can tell the sender's text from instructions.
    return (
        "Prepare a reply to this employee email.\n\n"
        "<email>\n"
        f"From: {em['from_name']} <{em['from_address']}>\n"
        f"Subject: {em['subject']}\n\n"
        f"{em['body']}\n"
        "</email>")


def reply_subject(em: dict, needs_review: bool) -> str:
    subject = em["subject"] or "(no subject)"
    if not re.match(r"(?i)re:", subject):
        subject = f"Re: {subject}"
    return f"{REVIEW_TAG} {subject}" if needs_review else subject


def preview(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= PREVIEW_CHARS else one_line[:PREVIEW_CHARS] + "..."


# ---------------------------------------------------------------------------
# Where drafts go: a local file (--email) or a Gmail draft (--inbox)
# ---------------------------------------------------------------------------

class LocalDrafts:
    """--email mode: write the draft to week-04/drafts/. Saves only; never sends."""

    def __init__(self, email_path: Path):
        self.email_path = email_path

    def save(self, em: dict, reply_text: str, needs_review: bool) -> tuple[str, str]:
        DRAFTS_DIR.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = DRAFTS_DIR / f"{self.email_path.stem}-{stamp}.txt"
        text = ("DRAFT - NOT SENT\n"
                f"To: {em['from_name']} <{em['from_address']}>\n"
                f"Subject: {reply_subject(em, needs_review)}\n"
                f"Needs human review: {'YES' if needs_review else 'no'}\n"
                f"Source email: {self.email_path.name}\n"
                f"Model: {MODEL}\n"
                "\n" + reply_text.strip() + "\n")
        path.write_text(text, encoding="utf-8")
        where = path.relative_to(HERE.parent).as_posix()
        return f"Draft saved to {where}. It was not sent.", f"Draft ({where}):\n{text}"


class GmailDrafts:
    """--inbox mode: create a Gmail draft in the sender's thread. Creates only; never sends."""

    def __init__(self, imap: imaplib.IMAP4_SSL, account: str, drafts_mailbox: str):
        self.imap = imap
        self.account = account
        self.drafts_mailbox = drafts_mailbox

    def save(self, em: dict, reply_text: str, needs_review: bool) -> tuple[str, str]:
        msg = EmailMessage()
        msg["From"] = self.account
        msg["To"] = formataddr((em["from_name"], em["from_address"]))
        msg["Subject"] = reply_subject(em, needs_review)
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.account.split("@")[-1])
        if em["message_id"]:  # threading: point back at the email being answered
            msg["In-Reply-To"] = em["message_id"]
            msg["References"] = f"{em['references']} {em['message_id']}".strip()
        msg.set_content(reply_text.strip() + "\n")

        # Gmail shows IMAP's \Flagged as a star, so drafts that need review are starred.
        flags = r"(\Draft \Flagged)" if needs_review else r"(\Draft)"
        status, data = self.imap.append(quote_mailbox(self.drafts_mailbox), flags,
                                        imaplib.Time2Internaldate(time.time()),
                                        msg.as_bytes(policy=email.policy.SMTP))
        if status != "OK":
            detail = data[0].decode("utf-8", "replace") if data and data[0] else status
            raise RuntimeError(f"Gmail did not accept the draft: {detail}")
        thread_note = "" if em["message_id"] else " (the original had no Message-ID, so it may not join the thread)"
        star_note = ", starred" if needs_review else ""
        shown = ("GMAIL DRAFT - NOT SENT\n"
                 f"To: {msg['To']}\n"
                 f"Subject: {msg['Subject']}\n"
                 f"Needs human review: {'YES (starred)' if needs_review else 'no'}\n"
                 "\n" + reply_text.strip() + "\n")
        return (f"Gmail draft created in {self.drafts_mailbox}{star_note}{thread_note}. It was not sent.",
                f"Gmail draft ({self.drafts_mailbox}){thread_note}:\n{shown}")


def quote_mailbox(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_drafts_mailbox(imap: imaplib.IMAP4_SSL) -> str:
    """Gmail marks its drafts folder with \\Drafts; its name depends on the account's language."""
    status, data = imap.list()
    if status == "OK":
        for line in data or []:
            text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
            m = re.match(r'^\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', text)
            if m and "\\drafts" in m.group("flags").lower():
                name = m.group("name").strip()
                if name.startswith('"') and name.endswith('"'):
                    name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                return name
    return "[Gmail]/Drafts"


# ---------------------------------------------------------------------------
# One agent run (one email)
# ---------------------------------------------------------------------------

async def run_agent(client: anthropic.AsyncAnthropic, em: dict, drafts) -> dict:
    system_prompt = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    print(f"From:    {em['from_name']} <{em['from_address']}>")
    print(f"Subject: {em['subject']}")
    print(f"Model:   {MODEL}\n")

    server = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER), "--as-employee", em["from_address"]],
        cwd=str(HERE.parent))

    result = {"in": 0, "out": 0, "tool_calls": 0, "draft": None, "stop": "", "needs_review": None}

    with open(SERVER_LOG, "a", encoding="utf-8") as server_log:
        async with stdio_client(server, errlog=server_log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_tools = (await session.list_tools()).tools
                mcp_names = {t.name for t in mcp_tools}
                tools = [{"name": t.name, "description": t.description or "",
                          "input_schema": t.input_schema} for t in mcp_tools] + [SAVE_REPLY_TOOL]
                print("Tools offered: " + ", ".join(t["name"] for t in tools) + "\n")

                messages: list = [{"role": "user", "content": first_message(em)}]
                while True:
                    try:
                        response = await client.messages.create(
                            model=MODEL, max_tokens=MAX_TOKENS, system=system_prompt,
                            tools=tools, messages=messages)
                    except anthropic.AuthenticationError:
                        result["stop"] = "The API key in API-Key.txt was rejected."
                        break
                    except anthropic.RateLimitError:
                        result["stop"] = "Rate limited by the API; try again in a minute."
                        break
                    except anthropic.APIStatusError as e:
                        result["stop"] = f"API error {e.status_code}: {e.message}"
                        break
                    except anthropic.APIConnectionError:
                        result["stop"] = "Could not reach the Anthropic API (network error)."
                        break

                    result["in"] += response.usage.input_tokens
                    result["out"] += response.usage.output_tokens

                    for block in response.content:
                        if block.type == "text" and block.text.strip():
                            print(f"[Claude] {block.text.strip()}\n")

                    tool_uses = [b for b in response.content if b.type == "tool_use"]
                    if response.stop_reason != "tool_use" or not tool_uses:
                        reasons = {
                            "end_turn": "Claude replied without requesting a tool.",
                            "max_tokens": f"Claude's reply hit the {MAX_TOKENS}-token limit.",
                            "refusal": "Claude declined to respond (refusal).",
                        }
                        result["stop"] = reasons.get(
                            response.stop_reason,
                            f"Claude stopped with stop_reason '{response.stop_reason}'.")
                        if result["draft"] is None:
                            result["stop"] += " No draft was saved."
                        break

                    messages.append({"role": "assistant", "content": response.content})
                    results = []
                    for tu in tool_uses:
                        if result["tool_calls"] >= MAX_TOOL_CALLS:
                            break
                        result["tool_calls"] += 1
                        print(f"Step {result['tool_calls']}: {tu.name}")
                        print(f"  inputs: {json.dumps(tu.input, ensure_ascii=False)}")
                        is_error = False
                        if tu.name == "save_reply":
                            args = tu.input if isinstance(tu.input, dict) else {}
                            reply, review = args.get("reply_text"), args.get("needs_human_review")
                            if result["draft"] is not None:
                                text, is_error = "A draft was already saved; save_reply can be called only once.", True
                            elif not isinstance(reply, str) or not reply.strip() or not isinstance(review, bool):
                                text, is_error = ("save_reply needs reply_text (non-empty text) and "
                                                  "needs_human_review (true or false)."), True
                            else:
                                try:
                                    text, result["draft"] = drafts.save(em, reply, review)
                                    result["needs_review"] = review
                                except Exception as exc:
                                    text, is_error = f"Could not save the draft: {exc}", True
                        elif tu.name in mcp_names:
                            try:
                                r = await session.call_tool(tu.name, tu.input)
                                text = "\n".join(c.text for c in r.content if getattr(c, "type", "") == "text")
                                is_error = bool(r.is_error)
                            except Exception as exc:  # keep the loop alive; report to Claude
                                text, is_error = f"Tool failed: {exc}", True
                        else:
                            text, is_error = f"Unknown tool: {tu.name}", True
                        print(f"  result{' (error)' if is_error else ''}: {preview(text)}\n")
                        results.append({"type": "tool_result", "tool_use_id": tu.id,
                                        "content": text, "is_error": is_error})

                    if result["draft"] is not None:
                        result["stop"] = "The draft was saved with save_reply."
                        break
                    if result["tool_calls"] >= MAX_TOOL_CALLS:
                        result["stop"] = f"Reached the limit of {MAX_TOOL_CALLS} tool calls without saving a draft."
                        break
                    messages.append({"role": "user", "content": results})

    print("-" * 70)
    print(f"Stopped: {result['stop']}")
    print(f"Tool calls: {result['tool_calls']}")
    if result["draft"] is not None:
        print("\n" + result["draft"].rstrip())
    else:
        print("\nNo draft was saved.")
    print(f"\nTokens: {result['in']:,} input, {result['out']:,} output "
          f"({result['in'] + result['out']:,} total)")
    return result


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

async def run_one_file(email_path: Path) -> None:
    em = parse_email(email_path.read_bytes())
    if em is None:
        fail(f"Could not find a sender address in the From line of {email_path}")
    client = anthropic.AsyncAnthropic(api_key=load_api_key())
    print(f"Email:   {email_path}")
    await run_agent(client, em, LocalDrafts(email_path))


async def run_inbox() -> None:
    client = anthropic.AsyncAnthropic(api_key=load_api_key())
    try:
        account, password = load_inbox.read_login()
    except load_inbox.LoginFileError as exc:
        fail(str(exc))
    OUT.hide(account, "[sandbox account]")

    print(f"Signing in to {load_inbox.IMAP_HOST} ...")
    try:
        imap = imaplib.IMAP4_SSL(load_inbox.IMAP_HOST, load_inbox.IMAP_PORT)
    except OSError as exc:
        fail(f"Could not connect to {load_inbox.IMAP_HOST}: {exc}")
    try:
        try:
            imap.login(account, password)
        except imaplib.IMAP4.error as exc:
            fail("Sign-in failed. Gmail said: " + load_inbox.login_error_text(exc, account) + "\n"
                 "Check the address and app password in Agent-Email.txt "
                 "(Gmail needs an app password, not the account password).")
        finally:
            del password
        print("Signed in.")

        status, _ = imap.select(load_inbox.MAILBOX)
        if status != "OK":
            fail(f"Could not open {load_inbox.MAILBOX}.")
        status, data = imap.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            fail("Could not search the inbox for unread email.")
        uids = data[0].split() if data and data[0] else []
        drafts = GmailDrafts(imap, account, find_drafts_mailbox(imap))
        print(f"Unread emails in {load_inbox.MAILBOX}: {len(uids)}. Drafts go to {drafts.drafts_mailbox}.\n")

        summary = []
        total_in = total_out = 0
        for n, uid in enumerate(uids, 1):
            print("=" * 70)
            print(f"Email {n} of {len(uids)}")
            # Mark as read first, so this email is never handled twice.
            status, _ = imap.uid("STORE", uid, "+FLAGS", r"(\Seen)")
            if status != "OK":
                print("Could not mark it as read, so it was skipped.\n")
                summary.append((n, "?", "skipped: could not mark as read"))
                continue
            status, data = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((part[1] for part in (data or []) if isinstance(part, tuple)), None)
            if status != "OK" or raw is None:
                print("Could not download it, so it was skipped (it is now marked read).\n")
                summary.append((n, "?", "skipped: could not download"))
                continue
            em = parse_email(raw)
            if em is None:
                print("It has no sender address, so it was skipped (it is now marked read).\n")
                summary.append((n, "?", "skipped: no sender address"))
                continue
            try:
                r = await run_agent(client, em, drafts)
            except Exception as exc:
                print(f"This run failed: {type(exc).__name__}: {exc} (the email stays marked read).\n")
                summary.append((n, em["subject"], f"failed: {type(exc).__name__}"))
                continue
            total_in += r["in"]
            total_out += r["out"]
            if r["draft"] is None:
                outcome = "no draft"
            else:
                outcome = "draft created" + (f", {REVIEW_TAG}, starred" if r["needs_review"] else "")
            summary.append((n, em["subject"], f"{outcome} ({r['tool_calls']} tool calls)"))
            print()

        print("=" * 70)
        print("Summary")
        if not summary:
            print("  No unread emails; nothing to do.")
        for n, subject, outcome in summary:
            print(f"  {n}. {subject}: {outcome}")
        print(f"\nTotal tokens: {total_in:,} input, {total_out:,} output ({total_in + total_out:,} total)")
        print("Nothing was sent. Review the drafts in Gmail.")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def open_save_file(name: str):
    path = Path(name).expanduser().resolve()
    protected = {KEY_FILE.resolve(), load_inbox.LOGIN_FILE.resolve()}
    if path in protected:
        fail("--save cannot write to a secrets file.")
    try:
        return open(path, "w", encoding="utf-8"), path
    except OSError as exc:
        fail(f"Could not open {name} for writing: {exc.strerror}")


def main() -> None:
    OUT.console.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout = OUT

    ap = argparse.ArgumentParser(description="Prepare draft replies to HR emails (never sends).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--email", metavar="FILE", help="handle one .eml email file; draft goes to week-04/drafts/")
    mode.add_argument("--inbox", action="store_true",
                      help="handle each unread email in the Gmail sandbox inbox; drafts go to Gmail")
    ap.add_argument("--save", metavar="FILE", help="also write everything printed to this UTF-8 text file")
    args = ap.parse_args()

    save_path = None
    if args.save:
        OUT.file, save_path = open_save_file(args.save)
    try:
        print(f"HR email agent - {datetime.datetime.now():%Y-%m-%d %H:%M}\n")
        if args.inbox:
            asyncio.run(run_inbox())
        else:
            email_path = Path(args.email).expanduser().resolve()
            if not email_path.is_file():
                fail(f"Email file not found: {args.email}")
            asyncio.run(run_one_file(email_path))
    finally:
        if OUT.file:
            OUT.file.close()
            OUT.file = None
            OUT.console.write(f"\nOutput also saved to {save_path}\n")


if __name__ == "__main__":
    main()
