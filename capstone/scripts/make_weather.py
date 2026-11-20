"""Build inputs/weather.json for the Fort GBUS event week (Mon Nov 30 - Sat Dec 5, 2026).

Run (from the repository folder, GBUS-652-Coursework):
    .venv\\Scripts\\python.exe capstone\\scripts\\make_weather.py

Source: the public National Weather Service forecast for Rochester, NY (KROC airport grid point
BUF 75,62), downloaded 2026-11-19 and saved in inputs/nws-snapshot-2026-11-19/. The forecast for
Mon Nov 23 onward is moved +7 days onto the event week (Nov 23 -> Nov 30, ..., Nov 28 -> Dec 5).
Each hourly entry says where it came from:
  - "NWS hourly"  : the NWS hourly forecast (covers up to Thu Dec 3, 03:00 after the shift)
  - "NWS grid"    : the NWS grid forecast (temperature, wind, gusts, sky cover, precipitation),
                    which runs a little longer (to Thu Dec 3, 19:00)
  - "notional"    : made-up late-fall values where the forecast does not reach (Thu evening - Sat),
                    and the fog added for event 03. Notional entries are marked "notional": true.
The data is notional for this exercise: built once, not refreshed.
Visibility: NWS gives only a placeholder (16 km all week), so visibility is set from the forecast
words (snow showers lower it). Waves: the airport grid point has no lake waves, so wave height
is estimated from the wind. Daylight is computed for Fort GBUS (about 43.2 N, 77.6 W).
Writes inputs/weather.json (overwrites).
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "inputs" / "nws-snapshot-2026-11-19"
OUT = ROOT / "inputs" / "weather.json"

SHIFT = timedelta(days=7)                       # forecast day -> event day
EST = timezone(timedelta(hours=-5))             # all event times are local standard time
WEEK_START = datetime(2026, 11, 30, 0, 0)       # event week, local
WEEK_END = datetime(2026, 12, 6, 0, 0)
LAT, LON = 43.2, -77.6

# Fog for event 03 (Tue Dec 1, 06:42): notional, to create the conditions the event needs.
FOG = [  # (from, to, visibility km, sky)
    (datetime(2026, 12, 1, 5, 0), datetime(2026, 12, 1, 8, 0), 0.8, "Dense fog"),
    (datetime(2026, 12, 1, 8, 0), datetime(2026, 12, 1, 9, 0), 2.5, "Fog lifting"),
]
FOG_NOTE = "Notional fog added for event 03 (pre-dawn fog over the lake); not in the NWS forecast."

# Notional days (after the forecast runs out): sky by day/night, temperatures, wind.
NOTIONAL_DAYS = {
    date(2026, 12, 3): dict(day_sky="Partly Sunny", night_sky="Partly Cloudy", tmin=-1, tmax=4,
                            wind=4.0, gust=7.0, dir="W", pop=5),
    date(2026, 12, 4): dict(day_sky="Mostly Cloudy", night_sky="Mostly Cloudy", tmin=1, tmax=6,
                            wind=6.0, gust=10.0, dir="SW", pop=15),
    date(2026, 12, 5): dict(day_sky="Partly Sunny", night_sky="Mostly Clear", tmin=-1, tmax=3,
                            wind=5.0, gust=8.0, dir="W", pop=10),
}

MPH = 0.44704
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW",
           "W", "WNW", "NW", "NNW"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def local(iso: str) -> datetime:
    """NWS ISO time -> naive local standard time."""
    return datetime.fromisoformat(iso).astimezone(EST).replace(tzinfo=None)


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


def mph(text: str) -> float:
    """'9 to 15 mph' -> the larger number, in m/s."""
    nums = [float(n) for n in re.findall(r"\d+", text)]
    return round(max(nums) * MPH, 1) if nums else 0.0


def grid_series(grid: dict, key: str) -> list[tuple[datetime, datetime, float]]:
    """NWS grid values -> [(start, end, value)] in local time. Duration like PT1H / PT6H / P1DT2H."""
    out = []
    for v in grid.get(key, {}).get("values", []):
        start_s, dur_s = v["validTime"].split("/")
        m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", dur_s)
        d, h, mi = (int(x) if x else 0 for x in m.groups())
        start = local(start_s)
        out.append((start, start + timedelta(days=d, hours=h, minutes=mi), v["value"]))
    return out


def at(series, t: datetime):
    for s, e, v in series:
        if s <= t < e:
            return v
    return None


def sky_from_cover(pct: float, daytime: bool) -> str:
    if pct < 12:
        return "Sunny" if daytime else "Clear"
    if pct < 38:
        return "Mostly Sunny" if daytime else "Mostly Clear"
    if pct < 63:
        return "Partly Sunny" if daytime else "Partly Cloudy"
    if pct < 88:
        return "Mostly Cloudy"
    return "Cloudy"


def visibility_km(sky: str) -> float:
    s = sky.lower()
    if "fog" in s:
        return 1.0
    if "snow" in s:
        if "slight chance" in s:
            return 12.0
        if "chance" in s:
            return 8.0
        return 3.0
    if "rain" in s or "drizzle" in s:
        return 10.0
    return 16.0                                  # NWS "10 statute miles" = unlimited for us


def waves_m(wind_mps: float) -> float:
    for limit, h in ((3, 0.2), (6, 0.5), (9, 1.0), (12, 1.5)):
        if wind_mps < limit:
            return h
    return 2.5


def sun_times(day: date) -> dict:
    """Sunrise / sunset and civil twilight (sun 6 deg below) in local standard time (NOAA method)."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat = math.radians(LAT)

    def times(zenith_deg: float) -> tuple[datetime, datetime]:
        ha = math.degrees(math.acos(math.cos(math.radians(zenith_deg)) / (math.cos(lat) * math.cos(decl))
                                    - math.tan(lat) * math.tan(decl)))
        noon = 720 - 4 * LON - eqt                 # minutes after midnight UTC
        base = datetime(day.year, day.month, day.day) - timedelta(hours=5)
        return (base + timedelta(minutes=noon - 4 * ha), base + timedelta(minutes=noon + 4 * ha))

    rise, sset = times(90.833)
    dawn, dusk = times(96.0)
    return {"civil_dawn": dawn, "sunrise": rise, "sunset": sset, "civil_dusk": dusk}


def light(t: datetime) -> str:
    s = {k: v.replace(second=0, microsecond=0) for k, v in sun_times(t.date()).items()}   # same minute as the cuts
    if s["sunrise"] <= t < s["sunset"]:
        return "day"
    if s["civil_dawn"] <= t < s["civil_dusk"]:
        return "twilight"
    return "night"


def pieces(t: datetime) -> list[tuple[datetime, datetime]]:
    """The hour [t, t+1h), split at dawn / sunrise / sunset / dusk (to the minute) if one falls inside."""
    end = t + timedelta(hours=1)
    cuts = sorted(v.replace(second=0, microsecond=0) for v in sun_times(t.date()).values()
                  if t < v.replace(second=0, microsecond=0) < end)
    edges = [t] + cuts + [end]
    return list(zip(edges, edges[1:]))


def compass(deg: float | None) -> str:
    return "calm" if deg is None else COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def summary(e: dict) -> str:
    gust = f" (gusts {e['gust_mps']:g})" if e.get("gust_mps") else ""
    return (f"{e['sky']}, {e['temperature_c']:g} °C, wind {e['wind_dir']} {e['wind_mps']:g} m/s{gust}, "
            f"visibility {e['visibility_km']:g} km, {e['light']}")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def main() -> None:
    hourly = json.loads((SNAP / "hourly.json").read_text(encoding="utf-8"))["properties"]
    grid = json.loads((SNAP / "grid.json").read_text(encoding="utf-8"))["properties"]
    issued = hourly.get("updateTime", "2026-11-19")
    gusts = grid_series(grid, "windGust")          # km/h
    g_temp, g_wind = grid_series(grid, "temperature"), grid_series(grid, "windSpeed")
    g_dir, g_sky = grid_series(grid, "windDirection"), grid_series(grid, "skyCover")
    g_pop = grid_series(grid, "probabilityOfPrecipitation")

    by_hour = {}
    for p in hourly["periods"]:
        by_hour[local(p["startTime"]) + SHIFT] = p

    entries = []
    t = WEEK_START
    while t < WEEK_END:
        real = t - SHIFT                            # the forecast hour this event hour comes from
        p = by_hour.get(t)
        lt = light(t + timedelta(minutes=30))       # sky words (Sunny / Clear) follow mid-hour light
        e: dict
        if p:
            wind = mph(p["windSpeed"])
            g = at(gusts, real)
            e = {"source": f"NWS hourly forecast, Rochester KROC (issued {issued[:16].replace('T', ' ')} UTC), "
                           f"for {fmt(real)[:16]}",
                 "notional": False, "sky": p["shortForecast"],
                 "temperature_c": round((p["temperature"] - 32) * 5 / 9, 1) if p.get("temperatureUnit", "F") == "F"
                 else p["temperature"],
                 "wind_mps": wind, "wind_dir": p["windDirection"] or "calm",
                 "gust_mps": round(g / 3.6, 1) if g and g / 3.6 > wind + 1 else None,
                 "precip_chance_pct": (p.get("probabilityOfPrecipitation") or {}).get("value") or 0}
        elif at(g_temp, real) is not None and at(g_wind, real) is not None and at(g_sky, real) is not None:
            wind = round(at(g_wind, real) / 3.6, 1)
            g = at(gusts, real)
            e = {"source": f"NWS grid forecast, Rochester KROC (issued {issued[:16].replace('T', ' ')} UTC), "
                           f"for {fmt(real)[:16]}",
                 "notional": False, "sky": sky_from_cover(at(g_sky, real), lt == "day"),
                 "temperature_c": round(at(g_temp, real), 1), "wind_mps": wind,
                 "wind_dir": compass(at(g_dir, real)) if wind > 0.5 else "calm",
                 "gust_mps": round(g / 3.6, 1) if g and g / 3.6 > wind + 1 else None,
                 "precip_chance_pct": at(g_pop, real) or 0}
        else:
            nd = NOTIONAL_DAYS[t.date()]
            hour = t.hour + 0.5                     # temperature: low near 07:00, high near 14:00
            frac = (1 - math.cos(math.pi * (hour - 7) / 7)) / 2 if 7 <= hour <= 14 else \
                   (1 + math.cos(math.pi * (hour - 14) / 17)) / 2 if hour > 14 else \
                   (1 + math.cos(math.pi * (hour + 10) / 17)) / 2
            e = {"source": "notional (the NWS forecast does not reach this day)", "notional": True,
                 "sky": nd["day_sky"] if lt == "day" else nd["night_sky"],
                 "temperature_c": round(nd["tmin"] + (nd["tmax"] - nd["tmin"]) * frac, 1),
                 "wind_mps": nd["wind"], "wind_dir": nd["dir"], "gust_mps": nd["gust"],
                 "precip_chance_pct": nd["pop"]}
        e["visibility_km"] = visibility_km(e["sky"])
        for f_from, f_to, vis, sky in FOG:
            if f_from <= t < f_to:
                e.update(sky=sky, visibility_km=vis, wind_mps=min(e["wind_mps"], 1.5), wind_dir="calm"
                         if min(e["wind_mps"], 1.5) < 1 else e["wind_dir"], gust_mps=None,
                         notional=True, adjusted=True, adjusted_note=FOG_NOTE)
        e["wave_height_m"] = waves_m(e["wind_mps"])
        for a, b in pieces(t):                      # split at dawn / sunrise / sunset / dusk
            piece = {"from": fmt(a), "to": fmt(b), **e, "light": light(a)}
            piece["summary"] = summary(piece)
            entries.append(piece)
        t += timedelta(hours=1)

    days = []
    d = WEEK_START.date()
    while d < WEEK_END.date():
        s = sun_times(d)
        days.append({"date": d.isoformat(), **{k: v.strftime("%H:%M") for k, v in s.items()}})
        d += timedelta(days=1)

    data = {
        "about": ("Fort GBUS weather for the event week Mon Nov 30 - Sat Dec 5, 2026 (local standard time). "
                  "Built from the public NWS forecast for Rochester, NY, issued 2026-11-19, moved +7 days "
                  "(Nov 23 -> Nov 30). Entries marked notional are made up for the exercise. All data is "
                  "notional for this course."),
        "units": {"temperature_c": "deg C", "wind_mps": "m/s sustained", "gust_mps": "m/s",
                  "visibility_km": "km", "wave_height_m": "m (estimated from wind)",
                  "precip_chance_pct": "%", "light": "day / twilight / night"},
        "rules_that_use_this": "ROE-5.6 interceptor: no if sustained wind > 15 m/s. ROE-5.10 laser: no if "
                               "visibility < 3 km. ROE-7.5: fog, snow and haze reduce camera and laser use; "
                               "high waves add radar sea clutter.",
        "days": days,
        "entries": entries,
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    hours = {e["from"][:13] for e in entries}
    print(f"{len(hours)} hours; split at dawn/sunrise/sunset/dusk into {len(entries)} entries")
    n_h = sum(e["source"].startswith("NWS hourly") for e in entries)
    n_g = sum(e["source"].startswith("NWS grid") for e in entries)
    n_n = sum(e["source"].startswith("notional") for e in entries)
    n_f = sum(bool(e.get("adjusted")) for e in entries)
    print(f"Wrote {OUT} : {len(entries)} entries ({n_h} NWS hourly, {n_g} NWS grid, {n_n} notional days; "
          f"{n_f} of the NWS entries have notional fog added)")


if __name__ == "__main__":
    main()
