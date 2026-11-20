"""Fort GBUS MCP server: the data tools for the counter-drone agents (stdio).

Start it (normally the agent pipeline starts it for you):
    .venv\\Scripts\\python.exe capstone\\app\\fgb_mcp_server.py --role analyst --clock PATH

--role analyst | reviewer | safety
    analyst and reviewer get the 7 shared tools. safety also gets get_control_room_info.
    The control-room tool does not exist for the other roles, so they cannot call it.
--clock PATH
    JSON file {"event_id": "07", "now": "2026-12-03 08:20:40"} written by the pipeline before
    each step. Every tool refuses times after "now" and other events. Read on every call.
    Without --clock, tools are unrestricted (testing only).

The tool descriptions below are the agent-facing text from prompts/tools.md.
No API key is needed: the server only looks things up.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import fgb_data as D
import fgb_rules

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def build_server(role: str, clock_path: Path | None) -> MCPServer:
    def clock() -> D.Clock:
        return D.Clock.from_file(clock_path)

    def guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (D.ToolInputError, fgb_rules.SearchUnavailable) as exc:
            raise ToolError(str(exc)) from exc

    def get_sensor_readings(event_id: str, up_to_time: str) -> dict:
        """Get the sensor readings for one drone event, from the start of the event up to a
        given time ('YYYY-MM-DD HH:MM:SS'). Readings after that time are never returned. Each
        reading is one sensor's report on one track at one moment: position (grid meters),
        altitude, heading, speed, confidence, and sensor-specific fields (control link,
        Remote ID, pilot position, blade spin, and so on). Empty fields are left out.
        Call this first."""
        return guard(D.get_sensor_readings, event_id, up_to_time, clock=clock())

    def get_health_status(time: str) -> dict:
        """Get the status (operational, degraded, down, unknown) of every sensor and defeat
        option at a given time, with the reason and health ID (H-xx) for anything not
        operational. Equipment without a health ID is operational."""
        return guard(D.get_health_status, time, clock=clock())

    def get_weather(time: str) -> dict:
        """Get the weather and lighting at a given time: visibility, wind, waves,
        precipitation, sunrise and sunset, and day/night/twilight. Visibility and wind limit
        some defeat options."""
        return guard(D.get_weather, time, clock=clock())

    def get_notices(time: str) -> dict:
        """Get the time-based notices (N-xx) in effect at a given time: alert level, the
        base's own drone flights, laser satellite-pass windows, airfield status, shipping,
        shoreline work, the regatta, and outside-agency contacts. Notices with a grid area
        include it."""
        return guard(D.get_notices, time, clock=clock())

    def check_site_zone(x: float, y: float) -> dict:
        """Find which Fort GBUS zone(s) a grid position (meters) is in, with ground-hazard and
        backstop ratings, and the distance to the nearest critical asset (ROE-2.7). Use it
        for what lies below a drone or a pilot."""
        return guard(D.check_site_zone, x, y)

    def check_line_of_fire(option_id: str, x: float, y: float, altitude: float,
                           time: str = "") -> dict:
        """Calculate the exact geometry from a defeat option (D-LAS, D-GUN, D-JAM, D-INT) to a
        target: bearing, elevation angle, distance; whether the target is inside the
        option's allowed sector and elevation limits; which zones lie along the line beyond
        the target; distances to the shipping lane, Canadian waters, marina, and fuel farm;
        and, if a time is given, any notice areas (such as a regatta) on the line. Use it
        before marking the laser or gun as allowed. Do not do this geometry yourself."""
        return guard(D.check_line_of_fire, option_id, x, y, altitude, time or None, clock=clock())

    def search_rules(query: str) -> dict:
        """Search the Fort GBUS standing rules of engagement and return the most relevant
        rules, each with its ID (ROE-x.y) and full text. Put rule IDs in the query (e.g.
        'ROE-5.7') to get those rules exactly. Use it to confirm what a rule says before
        citing it."""
        return guard(fgb_rules.search_rules, query)

    def get_control_room_info(event_id: str, time: str) -> dict:
        """Get information available only to the control room for this event up to a given
        time: patrol eyes-on reports, air traffic from the tower, outside-agency reports. Each
        entry has an ID (C-xx). This information must never be passed to the operator."""
        return guard(D.get_control_room_info, event_id, time, clock=clock())

    server = MCPServer(
        name=f"fort-gbus-{role}",
        instructions=("Fort GBUS counter-drone data tools. Use only facts from these tools. "
                      "All times are local; you cannot look past the current time."))
    shared = [
        (get_sensor_readings, "Get sensor readings"),
        (get_health_status, "Get equipment health"),
        (get_weather, "Get weather"),
        (get_notices, "Get notices"),
        (check_site_zone, "Check site zone"),
        (check_line_of_fire, "Check line of fire"),
        (search_rules, "Search rules"),
    ]
    for fn, title in shared:
        server.add_tool(fn, name=fn.__name__, title=title, annotations=READ_ONLY)
    if role == "safety":
        server.add_tool(get_control_room_info, name="get_control_room_info",
                        title="Get control-room information", annotations=READ_ONLY)
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Fort GBUS MCP server (stdio).")
    ap.add_argument("--role", choices=["analyst", "reviewer", "safety"], required=True)
    ap.add_argument("--clock", type=Path, help="clock file written by the pipeline")
    args = ap.parse_args()
    print(f"fort-gbus MCP server: role={args.role}, clock={args.clock or 'none (unrestricted)'}",
          file=sys.stderr)
    build_server(args.role, args.clock).run("stdio")


if __name__ == "__main__":
    main()
