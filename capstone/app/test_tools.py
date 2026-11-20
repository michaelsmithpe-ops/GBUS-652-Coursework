"""Check the Fort GBUS data tools against known answers from the scenario files.

Run:  .venv\\Scripts\\python.exe capstone\\app\\test_tools.py
No API calls. Needs the rules database (fgb_rules.py --rebuild) for the search tests.
"""

from __future__ import annotations

import asyncio
import sys

import fgb_data as D
import fgb_rules

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name, detail))


def raises(fn, *a, **k) -> str | None:
    try:
        fn(*a, **k)
    except D.ToolInputError as exc:
        return str(exc)
    return None


def status(time: str, eq: str) -> str:
    return D.get_health_status(time)["equipment"][eq]["status"]


def notice_ids(time: str) -> set[str]:
    return {n["notice_id"] for n in D.get_notices(time)["notices"]}


def zone_ids(x, y) -> set[str]:
    return {z["id"] for z in D.check_site_zone(x, y)["zones"]}


# --- 1. Sensor readings: only up to the requested time -----------------------------------
r = D.get_sensor_readings("07", "2026-12-03 08:20:40")
times = {x["Timestamp"] for x in r["readings"]}
check("readings: event 07 up to 08:20:40 returns 3 steps x 5 sensors",
      r["reading_count"] == 15 and max(times) == "2026-12-03 08:20:40", f"{r['reading_count']} readings")
r = D.get_sensor_readings("10", "2026-12-05 15:30:00")
check("readings: event 10 first step shows both tracks",
      {x.get("Track ID") for x in r["readings"]} >= {"T-1", "T-2"})
check("readings: empty cells are dropped",
      all(v != "" for row in r["readings"] for v in row.values()))

# --- 2. Clock: no peeking ahead, no other events ------------------------------------------
clk = D.Clock(event_id="10", now=D.parse_time("2026-12-05 15:30:20"))
check("clock: health at 15:31:00 refused when now = 15:30:20",
      raises(D.get_health_status, "2026-12-05 15:31:00", clock=clk) is not None)
check("clock: readings for another event refused",
      raises(D.get_sensor_readings, "07", "2026-12-03 08:22:00", clock=clk) is not None)
check("clock: health at 'now' allowed",
      raises(D.get_health_status, "2026-12-05 15:30:20", clock=clk) is None)

# --- 3. Equipment health -------------------------------------------------------------------
check("health: event 10 jammer operational at 15:30:40", status("2026-12-05 15:30:40", "D-JAM") == "operational")
check("health: event 10 jammer DOWN at 15:31:00 (H-06)", status("2026-12-05 15:31:00", "D-JAM") == "down")
check("health: event 09 interceptor operational (H-04 ended 11:00)", status("2026-12-04 12:00:00", "D-INT") == "operational")
check("health: event 03 laser DOWN (H-02)", status("2026-12-01 06:42:00", "D-LAS") == "down")
check("health: event 07 acoustic DEGRADED (H-03)", status("2026-12-03 08:20:00", "S-ACO") == "degraded")
check("health: event 01 wide-area camera operational (H-01 ended 09:30)", status("2026-11-30 10:15:00", "S-WAC") == "operational")

# --- 4. Notices ----------------------------------------------------------------------------
check("notices: event 08 has satellite window N-09", "N-09" in notice_ids("2026-12-03 16:50:00"))
check("notices: event 05 does NOT have N-07 (ended 11:28)", "N-07" not in notice_ids("2026-12-02 11:30:00"))
check("notices: event 04 has own flight N-03", "N-03" in notice_ids("2026-12-01 14:05:00"))
n10 = D.get_notices("2026-12-05 15:30:00")["notices"]
ids10 = {n["notice_id"] for n in n10}
check("notices: event 10 has regatta N-16 and airfield closed N-13", {"N-16", "N-13"} <= ids10)
check("notices: event 10 does NOT have N-11 (ended 15:24)", "N-11" not in ids10)
reg = next(n for n in n10 if n["notice_id"] == "N-16")
check("notices: regatta area parsed (x 0..2000, y 1000..3000)",
      reg.get("area") == {"x0": 0, "x1": 2000, "y0": 1000, "y1": 3000}, str(reg.get("area")))
check("notices: N-12 airfield ops NOT in effect Wed 21:10 (daily 07-18)", "N-12" not in notice_ids("2026-12-02 21:10:00"))
check("notices: N-12 airfield ops in effect Thu 08:20", "N-12" in notice_ids("2026-12-03 08:20:00"))
check("notices: event 01 work crew N-15 yes, satellite N-05 no",
      "N-15" in notice_ids("2026-11-30 10:15:00") and "N-05" not in notice_ids("2026-11-30 10:15:00"))
check("notices: alert ELEVATED (N-02) on Thursday", "N-02" in notice_ids("2026-12-03 08:20:00"))

# --- 5. Site zones -------------------------------------------------------------------------
check("zone: event 06 position is base housing", "Z-HOUSE" in zone_ids(-1500, -1850))
check("zone: fuel farm", "Z-FUEL" in zone_ids(2050, -700))
check("zone: event 09 pilot is in Canadian waters", "Z-CAN" in zone_ids(1500, 6400))
check("zone: open lake offshore", "Z-LAKE" in zone_ids(1200, 2500))
check("zone: Harborview is off base and critical", "Z-TOWN" in zone_ids(3200, -1200))

# --- 6. Line of fire -----------------------------------------------------------------------
lf = D.check_line_of_fire("D-LAS", -300, -250, 450)
check("line of fire: event 08 laser elevation ABOVE 45 deg limit",
      lf["checks"]["elevation_within_limit"]["ok"] is False, lf["checks"]["elevation_within_limit"]["detail"])
lf = D.check_line_of_fire("D-LAS", -1200, 1000, 120)
check("line of fire: event 05 laser elevation within limit (low, over water)",
      lf["checks"]["elevation_within_limit"]["ok"] is True, lf["checks"]["elevation_within_limit"]["detail"])
lf = D.check_line_of_fire("D-GUN", -1500, -1850, 90)
check("line of fire: event 06 gun OUTSIDE sector (target over housing)",
      lf["checks"]["inside_sector"]["ok"] is False, lf["checks"]["inside_sector"]["detail"])
lf = D.check_line_of_fire("D-GUN", 500, 2500, 300)
check("line of fire: gun north over lake is inside sector",
      lf["checks"]["inside_sector"]["ok"] is True, lf["checks"]["inside_sector"]["detail"])
lf = D.check_line_of_fire("D-GUN", 2600, 600, 100)
check("line of fire: event 10 T-2 near fuel farm, gun outside sector",
      lf["checks"]["inside_sector"]["ok"] is False, lf["checks"]["inside_sector"]["detail"])
lf = D.check_line_of_fire("D-LAS", 800, 1800, 100, time="2026-12-05 15:30:00")
check("line of fire: event 10 T-1 laser line hits regatta area N-16",
      any(h["notice_id"] == "N-16" for h in lf.get("notice_areas_on_line", [])))
lf = D.check_line_of_fire("D-JAM", 1200, 2500, 150)
check("line of fire: event 09 target ~1.5 km from shipping lane",
      1000 <= lf["target_distance_to"]["Z-SHIP"] <= 2000, f"{lf['target_distance_to']['Z-SHIP']} m")
check("line of fire: unknown option refused", raises(D.check_line_of_fire, "D-XYZ", 0, 0, 0) is not None)

# --- 7. Control-room information --------------------------------------------------------------
c = D.get_control_room_info("07", "2026-12-03 08:21:00")
check("control room: event 07 at 08:21:00 has no patrol report yet", c["entries"] == [])
c = D.get_control_room_info("07", "2026-12-03 08:22:00")
check("control room: event 07 at 08:22:00 has C-04 (walkers, pilot)",
      [e["control_room_id"] for e in c["entries"]] == ["C-04"])
c = D.get_control_room_info("10", "2026-12-05 15:31:20")
check("control room: event 10 helicopter C-07 visible at 15:31:20",
      "C-07" in {e["control_room_id"] for e in c["entries"]})

# --- 8. Rule search (RAG) ---------------------------------------------------------------------
rules = fgb_rules.load_rules()
import re as _re
expected = len(_re.findall(r"^\*\*ROE-\d+\.\d+", fgb_rules.RULES_FILE.read_text(encoding="utf-8"), _re.M))
check("rules: every rule in roe-standing.md parsed", len(rules) == expected,
      f"{len(rules)} parsed of {expected}")
r51 = next((x for x in rules if x["rule_id"] == "ROE-5.1"), None)
check("rules: untitled rule ROE-5.1 parsed with its own text",
      r51 is not None and "live control link" in r51["text"], r51["title"] if r51 else "missing")
r16 = next(n for n in D.load_notices() if n["notice_id"] == "N-16")
check("notices: wrapped lines kept (N-16 mentions spectators)", "Spectators" in " ".join(r16["text"]))
s = fgb_rules.search_rules("ROE-5.7")
check("rules: exact ID lookup ROE-5.7 first", s["results"][0]["rule_id"] == "ROE-5.7")
try:
    for q, want in [("laser elevation limit satellites", "ROE-5.7"),
                    ("jammer against a drone with no control link", "ROE-5.1"),
                    ("who is responsible for actions taken", "ROE-1.8"),
                    ("operator overrides the reviewer", "ROE-4.3"),
                    ("positive visual identification required for gun", "ROE-4.7")]:
        top = [x["rule_id"] for x in fgb_rules.search_rules(q)["results"]]
        check(f"rules: '{q}' finds {want} in top 4", want in top, ", ".join(top))
except fgb_rules.SearchUnavailable as exc:
    check("rules: semantic search available", False, str(exc))

# --- 9. MCP server: control-room tool only for the safety role ------------------------------
try:
    import fgb_mcp_server

    def tool_names(role):
        srv = fgb_mcp_server.build_server(role, None)
        return {t.name for t in asyncio.run(srv.list_tools())}

    a, s_ = tool_names("analyst"), tool_names("safety")
    check("server: analyst has 7 tools, no control-room tool",
          len(a) == 7 and "get_control_room_info" not in a, ", ".join(sorted(a)))
    check("server: safety has 8 tools incl. control-room tool",
          len(s_) == 8 and "get_control_room_info" in s_)
except Exception as exc:                       # report, don't crash the whole test run
    check("server: tool lists by role", False, f"{type(exc).__name__}: {exc}")

# --- 10. Weather: agents get conditions only; the viewer also gets where they came from --------
try:
    import json as _json
    srv = fgb_mcp_server.build_server("analyst", None)
    res = asyncio.run(srv.call_tool("get_weather", {"time": "2026-12-01 06:42:00"}))
    content = getattr(res, "content", None) or (res[0] if isinstance(res, tuple) else res)
    w = _json.loads("".join(getattr(c, "text", "") for c in content))
    c = w.get("conditions") or {}
    check("weather: tool returns conditions for event 03", w.get("available") is True and "summary" in c,
          c.get("summary", str(w)[:120]))
    check("weather: event 03 fog below the 3 km laser limit", c.get("visibility_km", 99) < 3)
    check("weather: agents' tool has NO source / notional / adjusted fields",
          not any(k in c for k in D.PROVENANCE_FIELDS), ", ".join(sorted(c)))
    full = D.get_weather("2026-12-01 06:42:00", full=True)["conditions"]
    check("weather: viewer (full=True) keeps source and notional",
          full.get("notional") is True and "source" in full and "adjusted_note" in full)
    check("weather: event 08 (16:50) is after sunset",
          D.get_weather("2026-12-03 16:50:00")["conditions"]["light"] == "twilight")
except Exception as exc:
    check("weather: MCP tool", False, f"{type(exc).__name__}: {exc}")

# --- Report ---------------------------------------------------------------------------------
passed = sum(ok for ok, _, _ in results)
for ok, name, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
