"""Escalation guardrail (week 6, Step 4): checks the analyst's recommendation IN CODE, after the
reviewer and before anything is shown to the operator or sent up to the control room.

BLOCKING rules (the rule the tool must never break: never escalate beyond what is allowed):
  (a) LADDER (ROE-4.1): the recommended rung may not exceed the highest rung the analyst's own
      threat level allows. The table is read from inputs/roe-standing.md (one source of truth).
  (b) STOP MEANS STOP (ROE-4.4): after the control room STOPS a rung-N request, nothing at rung N
      or higher goes forward for the rest of the event.
  A blocked recommendation is shown to the operator as DO NOT ENGAGE with a "GUARDRAIL:" reason,
  and an operator override cannot send a blocked rung to the control room.

WARNING checks (shown and logged; they never block):
  - EQUIPMENT: the recommended defeat option is down or not reporting in the health status.
  - PVID: laser or gun recommended, but no track has positive visual identification (ROE-4.7).
  - CITATIONS: a cited ROE / notice / health ID does not exist in the input files.

No API calls; standard library + fgb_data only.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

import fgb_data as D

THREATS = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
RUNG_OPTION = {3: "D-JAM", 4: "D-INT", 5: "D-LAS", 6: "D-GUN"}
_ID = re.compile(r"\b(ROE-\d+\.\d+|N-\d+|H-\d+)\b")


@lru_cache(maxsize=1)
def ladder() -> dict[int, str]:
    """{rung: minimum threat} from the ROE-4.1 table. 'Any' counts as NONE."""
    text = (D.INPUTS / "roe-standing.md").read_text(encoding="utf-8")
    out: dict[int, str] = {}
    for line in text.split("**ROE-4.1 Ladder.**", 1)[1].splitlines():
        if out and not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0].isdigit():
            out[int(cells[0])] = "NONE" if cells[2].lower() == "any" else cells[2].upper()
    if not out:
        raise RuntimeError("Could not read the ROE-4.1 ladder table from roe-standing.md")
    return out


def max_rung(threat: str) -> int:
    """Highest rung whose minimum threat is at or below this threat level."""
    level = THREATS.index(threat) if threat in THREATS else 0
    return max(r for r, need in ladder().items() if THREATS.index(need) <= level)


@lru_cache(maxsize=1)
def known_ids() -> frozenset[str]:
    roe = re.findall(r"\*\*(ROE-\d+\.\d+)\b", (D.INPUTS / "roe-standing.md").read_text(encoding="utf-8"))
    notices = re.findall(r"(?:\*\*|\|\s*)(N-\d+)\b", (D.INPUTS / "roe-notices.md").read_text(encoding="utf-8"))
    health = [e["id"] for e in json.loads((D.INPUTS / "health-status.json").read_text(encoding="utf-8"))["entries"]]
    return frozenset(roe + notices + health)


def blocking_reasons(rung: int, threat: str, stopped_rung: int | None, stopped_step: int | None) -> list[str]:
    """The blocking rules alone, for any requested rung (analyst's or an operator override's)."""
    out = []
    top = max_rung(threat)
    if rung > top:
        out.append(f"GUARDRAIL (ROE-4.1): rung {rung} needs a higher threat level; "
                   f"threat {threat} allows at most rung {top}.")
    if stopped_rung is not None and rung >= stopped_rung:
        out.append(f"GUARDRAIL (ROE-4.4): the control room stopped a rung {stopped_rung} request at step "
                   f"{stopped_step}; nothing at rung {stopped_rung} or higher goes forward in this event.")
    return out


def _warnings(a: dict, rung: int, now: str) -> list[str]:
    out = []
    opt = RUNG_OPTION.get(rung)
    if opt:
        eq = D.get_health_status(now)["equipment"].get(opt, {})
        if eq.get("status") in ("down", "unknown"):
            out.append(f"CHECK (equipment): {opt} is {eq['status'].upper()} at {now} "
                       f"({eq.get('health_id', 'health status')}).")
    if rung in (5, 6) and not any(t.get("pvid") for t in a.get("tracks", [])):
        out.append(f"CHECK (PVID, ROE-4.7): rung {rung} recommended but no track has PVID.")
    cited = " ".join(a.get("citations", []) + [c for o in a.get("options", []) for c in o.get("citations", [])])
    unknown = sorted(set(_ID.findall(cited)) - known_ids())
    if unknown:
        out.append(f"CHECK (citations): not found in the input files: {', '.join(unknown)}.")
    return out


def check(a: dict, now: str, stopped_rung: int | None = None, stopped_step: int | None = None) -> dict:
    """Check one analyst assessment. Returns {blocked, reasons, warnings, max_allowed}."""
    rung = a.get("recommended_rung", 0)
    threat = a.get("threat_level", "NONE")
    reasons = blocking_reasons(rung, threat, stopped_rung, stopped_step)

    try:
        warnings = _warnings(a, rung, now)
    except Exception as e:                                  # noqa: BLE001  (a warning must never stop a run)
        warnings = [f"CHECK: warning checks could not run ({type(e).__name__}: {e})."]

    allowed = max_rung(threat)
    if stopped_rung is not None:
        allowed = min(allowed, stopped_rung - 1)
    return {"blocked": bool(reasons), "reasons": reasons, "warnings": warnings, "max_allowed": allowed}
