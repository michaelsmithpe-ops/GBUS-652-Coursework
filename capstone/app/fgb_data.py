"""Fort GBUS data tools: plain Python functions that read the input files.

These are the functions behind the MCP server's tools (fgb_mcp_server.py). They make no
API calls and can be tested directly (test_tools.py).

Every time-based tool takes an explicit time and refuses times later than the clock's
"now", so an agent can never see the future (no peeking at later readings, equipment
faults, or control-room reports). Files are read fresh on every call.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "inputs"

WEEK_START = datetime(2026, 11, 30, 0, 0)
WEEK_END = datetime(2026, 12, 5, 23, 59, 59)
CRITICAL_ASSETS = ["Z-FUEL", "Z-HQ", "Z-HOUSE", "Z-AIR"]          # ROE-2.7
SENSORS = ["S-RF", "S-RAD", "S-ACO", "S-GIM", "S-WAC"]
DEFEAT = ["D-JAM", "D-INT", "D-LAS", "D-GUN"]


class ToolInputError(ValueError):
    """Bad input from the agent; the message is written for the agent to read."""


# ---------------------------------------------------------------------------
# Time and clock
# ---------------------------------------------------------------------------
def parse_time(value: str) -> datetime:
    value = value.strip().replace("T", " ").replace("*", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ToolInputError(f"Time '{value}' not understood. Use 'YYYY-MM-DD HH:MM:SS' (local time).")


def fmt_time(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Clock:
    """The pipeline's current event and time. None = unrestricted (testing only)."""
    event_id: str | None = None
    now: datetime | None = None

    @classmethod
    def from_file(cls, path: Path | None) -> "Clock":
        if path is None or not Path(path).exists():
            return cls()
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(event_id=d.get("event_id"), now=parse_time(d["now"]) if d.get("now") else None)

    def check(self, t: datetime, event_id: str | None = None) -> None:
        if self.now is not None and t > self.now:
            raise ToolInputError(
                f"Time {fmt_time(t)} is later than the current time {fmt_time(self.now)}. "
                "You can only look at information up to the current time.")
        if self.event_id is not None and event_id is not None and event_id != self.event_id:
            raise ToolInputError(f"You are assessing event {self.event_id}, not event {event_id}.")


# ---------------------------------------------------------------------------
# 1. Sensor readings
# ---------------------------------------------------------------------------
def get_sensor_readings(event_id: str, up_to_time: str, clock: Clock = Clock()) -> dict:
    t = parse_time(up_to_time)
    event_id = event_id.strip().zfill(2)
    clock.check(t, event_id)
    with open(INPUTS / "events.csv", newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["Event ID"] == event_id]
    if not rows:
        raise ToolInputError(f"No event '{event_id}'. Events are 01 to 10.")
    shown = [{k: v for k, v in r.items() if v not in ("", None)}       # drop empty cells
             for r in rows if parse_time(r["Timestamp"]) <= t]
    start = min(parse_time(r["Timestamp"]) for r in rows)
    out = {"event_id": event_id, "up_to_time": fmt_time(t), "event_start": fmt_time(start),
           "reading_count": len(shown), "readings": shown}
    if not shown:
        out["note"] = f"No readings yet: event {event_id} starts at {fmt_time(start)}."
    return out


# ---------------------------------------------------------------------------
# 2. Equipment health
# ---------------------------------------------------------------------------
def get_health_status(time: str, clock: Clock = Clock()) -> dict:
    t = parse_time(time)
    clock.check(t)
    data = json.loads((INPUTS / "health-status.json").read_text(encoding="utf-8"))
    status = {eq: {"status": "operational"} for eq in SENSORS + DEFEAT}
    for e in data["entries"]:
        if parse_time(e["from"]) <= t < parse_time(e["to"]):
            status[e["equipment"]] = {"status": e["status"], "health_id": e["id"],
                                      "reason": e["reason"], "effect": e["effect"],
                                      "from": e["from"], "to": e["to"]}
    return {"time": fmt_time(t), "equipment": status,
            "note": "Equipment not listed with a health ID is operational at this time."}


# ---------------------------------------------------------------------------
# 3. Weather (from inputs/weather.json, built by scripts/make_weather.py)
# ---------------------------------------------------------------------------
# Where an entry came from is for people (viewer, writeup), not for the agents: the agents treat
# the weather file as the truth, so these fields are removed from what the MCP tool returns.
PROVENANCE_FIELDS = ("source", "notional", "adjusted", "adjusted_note")


def get_weather(time: str, clock: Clock = Clock(), full: bool = False) -> dict:
    """Conditions for `time`. full=True (viewer only) keeps the provenance fields."""
    t = parse_time(time)
    clock.check(t)
    path = INPUTS / "weather.json"
    if not path.exists():
        return {"time": fmt_time(t), "available": False,
                "note": "Weather data is not available yet. Do not assume any weather; say "
                        "that visibility and wind are unknown and treat weather-dependent "
                        "options (laser, cameras, interceptor) with caution."}
    data = json.loads(path.read_text(encoding="utf-8"))
    best = None
    for e in data.get("entries", []):
        if parse_time(e["from"]) <= t < parse_time(e["to"]):
            best = e
    if best is not None and not full:
        best = {k: v for k, v in best.items() if k not in PROVENANCE_FIELDS}
    return {"time": fmt_time(t), "available": best is not None, "conditions": best}


# ---------------------------------------------------------------------------
# 4. Notices (parsed from roe-notices.md)
# ---------------------------------------------------------------------------
_HEADER = re.compile(r"^\*\*(N-\d+)\s+(.+?)\*\*\s*$")
_EFFECT = re.compile(r"In effect:\*\*\s*(.+)$")
_TABLE = re.compile(r"^\|\s*(N-\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|")
_AREA = re.compile(r"x\s*=\s*([−+\-]?[\d,]+)\s*to\s*([−+\-]?[\d,]+),\s*y\s*=\s*([−+\-]?[\d,]+)\s*to\s*([−+\-]?[\d,]+)")


def _num(s: str) -> float:
    return float(s.replace("−", "-").replace(",", "").replace("+", ""))


def _window(text: str) -> tuple[datetime, datetime, tuple[int, int] | None]:
    """'start – end', 'all week', with optional '(... HH:MM–HH:MM each day)'."""
    daily = None
    m = re.search(r"(\d{2}:\d{2})\s*[–-]\s*(\d{2}:\d{2})\s*each day", text)
    if m:
        h1, m1 = map(int, m.group(1).split(":"))
        h2, m2 = map(int, m.group(2).split(":"))
        daily = (h1 * 60 + m1, h2 * 60 + m2)
    text = re.sub(r"\(.*?\)", "", text).strip()
    if text.lower().startswith("all week"):
        return WEEK_START, WEEK_END, daily
    a, b = [p.strip() for p in re.split(r"\s+[–-]\s+", text, maxsplit=1)]
    return parse_time(a), parse_time(b), daily


def load_notices() -> list[dict]:
    notices, current, section = [], None, ""
    for raw in (INPUTS / "roe-notices.md").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section, current = line[3:].strip(), None
            continue
        if line == "---":
            current = None
            continue
        m = _HEADER.match(line)
        if m:
            current = {"notice_id": m.group(1), "title": m.group(2), "category": section, "text": []}
            notices.append(current)
            continue
        m = _TABLE.match(line)
        if m and m.group(1).startswith("N-"):
            start, end = parse_time(m.group(2)), parse_time(m.group(3))
            notices.append({"notice_id": m.group(1), "title": "Laser satellite-pass window",
                            "category": section, "start": start, "end": end, "daily": None,
                            "text": ["The laser may not fire during this window (ROE-5.8)."]})
            continue
        if current is not None and line.startswith("- "):
            m = _EFFECT.search(line)
            if m:
                current["start"], current["end"], current["daily"] = _window(m.group(1))
            else:
                current["text"].append(line[2:].replace("**", ""))
        elif current is not None and line and raw.startswith(" ") and current["text"]:
            # Indented continuation of the previous bullet (a wrapped line).
            current["text"][-1] += " " + line.replace("**", "")
    for n in notices:
        body = " ".join(n["text"])
        a = _AREA.search(body)
        n["area"] = ({"x0": _num(a.group(1)), "x1": _num(a.group(2)),
                      "y0": _num(a.group(3)), "y1": _num(a.group(4))} if a else None)
    return notices


def _in_effect(n: dict, t: datetime) -> bool:
    if not (n["start"] <= t <= n["end"]):
        return False
    if n.get("daily"):
        if t.weekday() >= 5:                     # "weekdays only"
            return False
        minutes = t.hour * 60 + t.minute
        return n["daily"][0] <= minutes < n["daily"][1]
    return True


def get_notices(time: str, clock: Clock = Clock()) -> dict:
    t = parse_time(time)
    clock.check(t)
    active = [{"notice_id": n["notice_id"], "title": n["title"], "category": n["category"],
               "in_effect": f"{fmt_time(n['start'])} to {fmt_time(n['end'])}",
               "text": " ".join(n["text"]), **({"area": n["area"]} if n["area"] else {})}
              for n in load_notices() if _in_effect(n, t)]
    return {"time": fmt_time(t), "notices": active,
            "note": "Only notices in effect at this time are listed."}


# ---------------------------------------------------------------------------
# 5-6. Site zones and line of fire
# ---------------------------------------------------------------------------
def load_site() -> dict:
    return json.loads((INPUTS / "site.json").read_text(encoding="utf-8"))


def _point_in_zone(z: dict, x: float, y: float) -> bool:
    if z["shape"] == "rect":
        return z["x0"] <= x <= z["x1"] and z["y0"] <= y <= z["y1"]
    inside, pts = False, z["points"]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _dist_to_rect(z: dict, x: float, y: float) -> float:
    dx = max(z["x0"] - x, 0, x - z["x1"])
    dy = max(z["y0"] - y, 0, y - z["y1"])
    return math.hypot(dx, dy)


def _zones_at(site: dict, x: float, y: float) -> list[dict]:
    found = [z for z in site["zones"] if _point_in_zone(z, x, y)]
    if not found:
        b = site["base_boundary"]
        on_base = b["x0"] <= x <= b["x1"] and b["y0"] <= y <= b["y1"]
        if y < site["shoreline_y"]:
            found = [{"id": "Z-OPEN" if on_base else "OFF-BASE-LAND",
                      "name": "Open base land" if on_base else "Off-base land (public)",
                      "ground_hazard": "Low" if on_base else "Unknown (public land)",
                      "backstop": "Conditional" if on_base else "Never"}]
    return found


def _zone_summary(z: dict) -> dict:
    return {k: z[k] for k in ("id", "name", "ground_hazard", "backstop", "condition") if k in z}


def check_site_zone(x: float, y: float) -> dict:
    site = load_site()
    zones = [_zone_summary(z) for z in _zones_at(site, x, y)]
    crit = {z["id"]: z for z in site["zones"] if z["id"] in CRITICAL_ASSETS}
    nearest = min(((zid, _dist_to_rect(z, x, y)) for zid, z in crit.items()), key=lambda p: p[1])
    return {"x": x, "y": y, "over_water": y > site["shoreline_y"], "zones": zones,
            "nearest_critical_asset": {"id": nearest[0], "name": crit[nearest[0]]["name"],
                                       "distance_m": round(nearest[1])}}


def _bearing(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dx, dy)) % 360


def _in_sector(b: float, b_from: float, b_to: float) -> bool:
    return (b - b_from) % 360 <= (b_to - b_from) % 360


def check_line_of_fire(option_id: str, x: float, y: float, altitude: float,
                       time: str | None = None, clock: Clock = Clock()) -> dict:
    site = load_site()
    opts = {d["id"]: d for d in site["defeat_options"]}
    option_id = option_id.strip().upper()
    if option_id not in opts:
        raise ToolInputError(f"Unknown option '{option_id}'. Use one of {', '.join(DEFEAT)}.")
    o, geo = opts[option_id], site["engagement_geometry"].get(option_id, {})
    dx, dy = x - o["x"], y - o["y"]
    ground = math.hypot(dx, dy)
    bearing = _bearing(dx, dy)
    elev = math.degrees(math.atan2(altitude - o["height"], ground))
    out = {"option_id": option_id, "from": {"x": o["x"], "y": o["y"], "height_m": o["height"]},
           "target": {"x": x, "y": y, "altitude_m": altitude},
           "bearing_deg": round(bearing, 1), "elevation_deg": round(elev, 1),
           "ground_distance_m": round(ground), "slant_distance_m": round(math.hypot(ground, altitude - o["height"])),
           "target_zones": [_zone_summary(z) for z in _zones_at(site, x, y)],
           "checks": {}, "rules": geo.get("rules", [])}

    checks = out["checks"]
    if "max_elevation" in geo:
        checks["elevation_within_limit"] = {
            "ok": elev <= geo["max_elevation"],
            "detail": f"{elev:.1f} deg vs. limit {geo['max_elevation']} deg"}
    if "min_elevation" in geo:
        checks["elevation_within_band"] = {
            "ok": geo["min_elevation"] <= elev <= geo["max_elevation"],
            "detail": f"{elev:.1f} deg vs. allowed {geo['min_elevation']}-{geo['max_elevation']} deg"}
    if "sector_from" in geo:
        checks["inside_sector"] = {
            "ok": _in_sector(bearing, geo["sector_from"], geo["sector_to"]),
            "detail": f"bearing {bearing:.0f} deg vs. sector {geo['sector_from']:03d}-{geo['sector_to']:03d} deg"}

    # Zones along the line beyond the target (horizontal projection), out to the danger range.
    if "danger_range_m" in geo and ground > 0:
        ux, uy = dx / ground, dy / ground
        seen, crossed = set(), []
        r = ground
        while r <= max(geo["danger_range_m"], ground):
            px, py = o["x"] + ux * r, o["y"] + uy * r
            for z in _zones_at(site, px, py):
                if z["id"] not in seen:
                    seen.add(z["id"])
                    crossed.append({**_zone_summary(z), "first_at_m_from_option": round(r)})
            r += 25
        out["zones_beyond_target"] = crossed
        never = [z["id"] for z in crossed if z["backstop"] == "Never"]
        checks["backstop_clear_of_never_zones"] = {
            "ok": not never,
            "detail": ("no 'Never' zones beyond the target" if not never
                       else f"line beyond target crosses: {', '.join(never)}")}

    # Distances that matter for the jammer and interceptor.
    zones = {z["id"]: z for z in site["zones"]}
    out["target_distance_to"] = {zid: round(_dist_to_rect(zones[zid], x, y))
                                 for zid in ("Z-SHIP", "Z-CAN", "Z-MARINA", "Z-FUEL") if zid in zones}

    # Time-based areas from notices (e.g. the regatta race area) along the line.
    if time:
        t = parse_time(time)
        clock.check(t)
        hits = []
        for n in load_notices():
            if n["area"] and _in_effect(n, t):
                a = n["area"]
                rect = {"x0": a["x0"], "x1": a["x1"], "y0": a["y0"], "y1": a["y1"]}
                end = max(geo.get("danger_range_m", ground), ground)
                samples = [(o["x"] + dx / ground * r, o["y"] + dy / ground * r)
                           for r in range(0, int(end) + 1, 25)] if ground > 0 else []
                target_inside = _dist_to_rect(rect, x, y) == 0
                if target_inside or any(_dist_to_rect(rect, px, py) == 0 for px, py in samples):
                    hits.append({"notice_id": n["notice_id"], "title": n["title"],
                                 "target_inside_area": target_inside})
        out["notice_areas_on_line"] = hits
        if hits:
            checks["clear_of_notice_areas"] = {
                "ok": False, "detail": "line crosses: " + ", ".join(h["notice_id"] for h in hits)}

    out["all_geometry_checks_ok"] = all(c["ok"] for c in checks.values()) if checks else None
    out["note"] = ("Geometry only. Also check people, vessels, and aircraft from notices and "
                   "sensor data, equipment health, weather, PVID, and the threat level.")
    return out


# ---------------------------------------------------------------------------
# 8. Control-room information (safety agent only; enforced by the MCP server)
# ---------------------------------------------------------------------------
def get_control_room_info(event_id: str, time: str, clock: Clock = Clock()) -> dict:
    t = parse_time(time)
    event_id = event_id.strip().zfill(2)
    clock.check(t, event_id)
    data = json.loads((INPUTS / "control-room-info.json").read_text(encoding="utf-8"))
    entries = [{"control_room_id": e["id"], "time": e["time"], "source": e["source"], "info": e["info"]}
               for e in data["entries"] if e["event"] == event_id and parse_time(e["time"]) <= t]
    return {"event_id": event_id, "time": fmt_time(t), "entries": entries,
            "visibility": "CONTROL ROOM ONLY. Never pass this to the operator."}
