"""Escalation guardrail (week 6, Step 4): checks the analyst's recommendation IN CODE, after the
reviewer and before anything is shown to the operator or sent up to the control room.

BLOCKING rules (the rule the tool must never break: never escalate beyond what is allowed):
  (a) LADDER (ROE-4.1): the recommended rung may not exceed the highest rung the analyst's own
      threat level allows. The table is read from inputs/roe-standing.md (one source of truth).
  (b) STOP MEANS STOP (ROE-4.4): after the control room STOPS a rung-N request, nothing at rung N
      or higher goes forward for the rest of the event.
  (c) SECTION 5 NUMBER RULES, from the input data, not the analyst's opinion. For every track
      the analyst calls an unknown drone (position from the latest sensor reading), the
      recommended option is blocked when:
        D-JAM  no live control link on the RF sensor in the last 60 s (ROE-5.1)
        D-INT  sustained wind above 15 m/s (ROE-5.6); over a Critical ground-hazard zone
               below threat HIGH (ROE-5.5)
        D-LAS  elevation above 45 deg (ROE-5.7); a satellite-pass window in effect (ROE-5.8);
               visibility below 3 km, or no current gimbal-camera view (ROE-5.10); the beam
               path crosses a 'Never' zone or a notice area with people or vessels (ROE-5.11)
        D-GUN  outside the 300-060 sector or the 5-30 deg band (ROE-5.12); the line of fire
               crosses a 'Never' zone or a notice area (ROE-5.13); the jammer, interceptor,
               or laser is still usable, so the gun is not the last resort (ROE-5.14)
      Uses only what the analyst can also see: never control-room information (C-xx), so
      nothing control-room-only is shown to the operator. Crewed-aircraft distances
      (ROE-5.2, 5.4, 5.9) are not in that data, so they stay with the agents and the
      control room.
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


# ---------------------------------------------------------------------------
# (c) Section 5 number rules
# ---------------------------------------------------------------------------
WIND_LIMIT_MPS = 15.0          # ROE-5.6
VISIBILITY_MIN_KM = 3.0        # ROE-5.10
CAMERA_MAX_AGE_S = 30          # ROE-2.4 / ROE-5.10: a current view
LINK_WINDOW_S = 60             # ROE-5.1: a live control link, recently reported


def _readings(event_id: str, now: str) -> list[dict]:
    return D.get_sensor_readings(event_id, now)["readings"]


def _age_s(now: str, ts: str) -> float:
    return (D.parse_time(now) - D.parse_time(ts)).total_seconds()


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def target_tracks(a: dict, event_id: str, now: str) -> list[dict]:
    """The tracks the analyst calls an unknown drone, each placed at its latest sensor position
    (lowest position error at the latest time). Tracks with no sensor position are skipped."""
    rows = [r for r in _readings(event_id, now) if r.get("Detection (Y/N)") == "Y"]
    out = []
    for t in a.get("tracks", []):
        if t.get("classification") != "unknown drone":
            continue
        tid = t.get("track_id", "")
        pos = [r for r in rows if r.get("Track ID") == tid and _f(r.get("X (m)")) is not None
               and _f(r.get("Y (m)")) is not None and _f(r.get("Altitude (m)")) is not None]
        if not pos:
            continue
        latest = max(r["Timestamp"] for r in pos)
        best = min((r for r in pos if r["Timestamp"] == latest),
                   key=lambda r: _f(r.get("Position error (m)")) or 1e9)
        out.append({"track_id": tid, "x": _f(best["X (m)"]), "y": _f(best["Y (m)"]),
                    "alt": _f(best["Altitude (m)"]), "sensor": best["Sensor ID"], "time": latest,
                    "rows": [r for r in rows if r.get("Track ID") == tid]})
    return out


def _option_problems(opt: str, trk: dict, a: dict, now: str, conditions: dict, notices: list[dict]) -> list[str]:
    """Section 5 rules broken by using `opt` against one track (rule ID first in each reason)."""
    x, y, alt, tid = trk["x"], trk["y"], trk["alt"], trk["track_id"]
    out = []
    if opt == "D-JAM":
        link = any(r["Sensor ID"] == "S-RF" and r.get("Control link present") == "Y"
                   and _age_s(now, r["Timestamp"]) <= LINK_WINDOW_S for r in trk["rows"])
        if not link:
            out.append(f"ROE-5.1: no live control link on {tid} (RF sensor, last {LINK_WINDOW_S} s)")
    elif opt == "D-INT":
        wind = _f(conditions.get("wind_mps"))
        if wind is not None and wind > WIND_LIMIT_MPS:
            out.append(f"ROE-5.6: sustained wind {wind:g} m/s is above {WIND_LIMIT_MPS:g} m/s")
        zones = D.check_site_zone(x, y)["zones"]
        crit = [z["id"] for z in zones if z.get("ground_hazard") == "Critical"]
        if crit and a.get("threat_level") not in ("HIGH", "CRITICAL"):
            out.append(f"ROE-5.5: {tid} is over Critical ground hazard ({', '.join(crit)}) "
                       f"and the threat is {a.get('threat_level')}, not HIGH or CRITICAL")
    elif opt in ("D-LAS", "D-GUN"):
        lof = D.check_line_of_fire(opt, x, y, alt, now)
        c = lof["checks"]
        if opt == "D-LAS":
            if not c.get("elevation_within_limit", {"ok": True})["ok"]:
                out.append(f"ROE-5.7: elevation to {tid} is {c['elevation_within_limit']['detail']}")
            sat = [n["notice_id"] for n in notices if "satellite" in n["title"].lower()]
            if sat:
                out.append(f"ROE-5.8: satellite-pass window in effect ({', '.join(sat)})")
            vis = _f(conditions.get("visibility_km"))
            if vis is not None and vis < VISIBILITY_MIN_KM:
                out.append(f"ROE-5.10: visibility {vis:g} km is below {VISIBILITY_MIN_KM:g} km")
            view = any(r["Sensor ID"] == "S-GIM" and r.get("Visual ID (Y/N)") == "Y"
                       and _age_s(now, r["Timestamp"]) <= CAMERA_MAX_AGE_S for r in trk["rows"])
            if not view:
                out.append(f"ROE-5.10: the gimbal camera has no current view of {tid} "
                           f"(last {CAMERA_MAX_AGE_S} s)")
            rule_path = "ROE-5.11"
        else:
            for k in ("inside_sector", "elevation_within_band"):
                if not c.get(k, {"ok": True})["ok"]:
                    out.append(f"ROE-5.12: {c[k]['detail']}")
            rule_path = "ROE-5.13"
        for k in ("backstop_clear_of_never_zones", "clear_of_notice_areas"):
            if not c.get(k, {"ok": True})["ok"]:
                out.append(f"{rule_path}: {c[k]['detail']}")
    return out


def section5_reasons(rung: int, a: dict, event_id: str, now: str) -> list[str]:
    """Blocking reasons from the Section 5 number rules for the option at this rung."""
    opt = RUNG_OPTION.get(rung)
    if not opt:
        return []
    tracks = target_tracks(a, event_id, now)
    conditions = D.get_weather(now).get("conditions") or {}
    notices = D.get_notices(now)["notices"]
    out = []
    for trk in tracks:
        problems = _option_problems(opt, trk, a, now, conditions, notices)
        if opt == "D-GUN":
            down = {k for k, v in D.get_health_status(now)["equipment"].items()
                    if v.get("status") in ("down", "unknown")}
            usable = [o for o in ("D-JAM", "D-INT", "D-LAS") if o not in down
                      and not _option_problems(o, trk, a, now, conditions, notices)]
            if usable:
                problems.append(f"ROE-5.14: the gun is not the last resort; still usable: {', '.join(usable)}")
        for p in problems:
            rule, detail = p.split(": ", 1)
            out.append(f"GUARDRAIL ({rule}): rung {rung} ({opt}) against {trk['track_id']}: {detail}.")
    return out


def blocking_reasons(rung: int, threat: str, stopped_rung: int | None, stopped_step: int | None,
                     a: dict | None = None, event_id: str | None = None, now: str | None = None) -> list[str]:
    """The blocking rules alone, for any requested rung (analyst's or an operator override's).
    With the assessment, event, and time, the Section 5 number rules (c) are checked too."""
    out = []
    top = max_rung(threat)
    if rung > top:
        out.append(f"GUARDRAIL (ROE-4.1): rung {rung} needs a higher threat level; "
                   f"threat {threat} allows at most rung {top}.")
    if stopped_rung is not None and rung >= stopped_rung:
        out.append(f"GUARDRAIL (ROE-4.4): the control room stopped a rung {stopped_rung} request at step "
                   f"{stopped_step}; nothing at rung {stopped_rung} or higher goes forward in this event.")
    if a is not None and event_id and now:
        out += section5_reasons(rung, a, event_id, now)
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


def check(a: dict, now: str, stopped_rung: int | None = None, stopped_step: int | None = None,
          event_id: str | None = None) -> dict:
    """Check one analyst assessment. Returns {blocked, reasons, warnings, max_allowed}."""
    rung = a.get("recommended_rung", 0)
    threat = a.get("threat_level", "NONE")
    reasons = blocking_reasons(rung, threat, stopped_rung, stopped_step)
    s5_error = None
    if event_id:
        try:
            reasons += section5_reasons(rung, a, event_id, now)
        except Exception as e:                              # noqa: BLE001  (unsure -> tell the people)
            s5_error = (f"CHECK: the Section 5 number checks could not run ({type(e).__name__}: {e}); "
                        f"check ROE Section 5 by hand.")

    try:
        warnings = _warnings(a, rung, now)
    except Exception as e:                                  # noqa: BLE001  (a warning must never stop a run)
        warnings = [f"CHECK: warning checks could not run ({type(e).__name__}: {e})."]
    if s5_error:
        warnings.append(s5_error)

    allowed = max_rung(threat)
    if stopped_rung is not None:
        allowed = min(allowed, stopped_rung - 1)
    return {"blocked": bool(reasons), "reasons": reasons, "warnings": warnings, "max_allowed": allowed}
