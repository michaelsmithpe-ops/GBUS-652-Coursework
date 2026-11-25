"""Alder Creek Heating & Cooling service desk assistant (week 6 lecture example).

Sends one customer service request to Claude with the system prompt in
assistant-prompt.txt followed by the service guide in service-guide.md,
and prints the JSON reply: {"priority", "reply", "needs_person"}.

Usage (from the repository folder):
    .venv\\Scripts\\python.exe week-06\\alder-creek\\assistant.py --request "Our heat isn't working."

The API key is read from API-Key.txt in the folder above the repository.
It is never printed, logged, or written to a file.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent             # week-06/alder-creek
REPO = HERE.parents[1]                             # GBUS-652-Coursework
KEY_FILE = REPO.parent / "API-Key.txt"             # folder above the repository
PROMPT_FILE = HERE / "assistant-prompt.txt"
GUIDE_FILE = HERE / "service-guide.md"

MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 1024

# --- Guardrails (in code, not in the prompt) ---------------------------------
# 1. Input: a safety request never reaches Claude; a fixed reply goes out instead.
SAFETY_RE = re.compile(r"\bgas\b|carbon\s+monoxide|\bsmok(?:e|es|ed|ing|y)\b|\bburn(?:ing|t|ed|s)?\b",
                       re.IGNORECASE)
SAFETY_REPLY = ("Please leave the building now and call the gas company or 911 from outside. "
                "Someone from Alder Creek will call you right away.")

# 2. Output: replies with any of these are held for a person.
ALLOWED_DOLLARS = {0, 89, 149, 129}
DOLLAR_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
BOOKED_RE = re.compile(r"\b(booked|confirmed)\b", re.IGNORECASE)
CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s?(?:a\.?m\.?|p\.?m\.?)(?![a-z])|\b(?:noon|midnight)\b",
                      re.IGNORECASE)
WARRANTY_RE = re.compile(r"\bcovered\b|\bunder\s+warranty\b", re.IGNORECASE)


def input_guardrail(request: str) -> dict | None:
    """Return the fixed Safety reply if the request mentions gas, CO, smoke, or burning."""
    if SAFETY_RE.search(request):
        return {"priority": "Safety", "reply": SAFETY_REPLY, "needs_person": True}
    return None


def output_guardrail(reply: dict) -> list[str]:
    """Return the reasons this reply must be held for a person (empty list = send it)."""
    text = str(reply.get("reply", ""))
    reasons = []
    bad = [a for a in DOLLAR_RE.findall(text) if float(a.replace(",", "")) not in ALLOWED_DOLLARS]
    if bad:
        reasons.append("dollar amount not on the fee list: " + ", ".join("$" + a for a in bad))
    words = sorted({m.lower() for m in BOOKED_RE.findall(text)})
    if words:
        reasons.append("says " + " / ".join(words))
    times = [m.group(0) for m in CLOCK_RE.finditer(text)]
    if times:
        reasons.append("gives a clock time: " + ", ".join(times))
    claims = sorted({m.group(0).lower() for m in WARRANTY_RE.finditer(text)})
    if claims:
        reasons.append("says " + " / ".join(claims))
    return reasons


def load_api_key() -> str:
    """Read the key from API-Key.txt. Never print, log, or save it."""
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        sys.exit(f"Could not read the API key file {KEY_FILE}.")
    if not key:
        sys.exit("The API key file is empty.")
    return key


def system_prompt() -> str:
    """The assistant prompt, followed by the full service desk guide."""
    prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()
    guide = GUIDE_FILE.read_text(encoding="utf-8").strip()
    return prompt + "\n\n" + guide


def parse_json(text: str) -> dict:
    """Parse the model's JSON reply; tolerate a ```json fence around it."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return json.loads(t)


def ask(request: str, client: anthropic.Anthropic | None = None) -> dict:
    """Send one service request; return the parsed JSON reply, after both guardrails."""
    fixed = input_guardrail(request)
    if fixed:                                   # guardrail 1: Claude is never called
        return fixed
    client = client or anthropic.Anthropic(api_key=load_api_key())
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt(),
        messages=[{"role": "user", "content": request}],
    )
    text = "".join(b.text for b in message.content if b.type == "text")
    try:
        reply = parse_json(text)
    except json.JSONDecodeError:
        sys.exit("Claude's reply was not valid JSON:\n" + text)
    held = output_guardrail(reply)              # guardrail 2: hold for a person
    if held:
        reply["needs_person"] = True
        reply["held_because"] = "; ".join(held)
    return reply


def main() -> None:
    parser = argparse.ArgumentParser(description="Alder Creek service desk assistant")
    parser.add_argument("--request", required=True, help="The customer's service request text")
    args = parser.parse_args()
    if not args.request.strip():
        sys.exit("The request is empty.")
    sys.stdout.reconfigure(encoding="utf-8")  # so °, — and other symbols print correctly
    print(json.dumps(ask(args.request), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
