# Tool Descriptions — Draft 1

Tools are not AI, but their **descriptions are prompts**: they are how an agent decides which
tool to call, when, and with what inputs. The **Description** text below is what the agent
sees. Inputs and returns will become the tool's schema in code.

## Who can use what

| Tool | Analyst | Reviewer | Safety agent |
|---|:-:|:-:|:-:|
| get_sensor_readings | ✓ | ✓ | ✓ |
| get_health_status | ✓ | ✓ | ✓ |
| get_weather | ✓ | ✓ | ✓ |
| get_notices | ✓ | ✓ | ✓ |
| check_site_zone | ✓ | ✓ | ✓ |
| check_line_of_fire | ✓ | ✓ | ✓ |
| search_rules | ✓ | ✓ | ✓ |
| get_control_room_info | — | — | ✓ |
| submit_assessment | ✓ | — | — |
| submit_review | — | ✓ | — |
| submit_advice | — | — | ✓ |

---

## Data tools (MCP server)

### get_sensor_readings
**Description:** Get the sensor readings for one drone event, from the start of the event up
to a given time. Readings after that time are never returned. Each reading is one sensor's
report on one track at one moment, with position, altitude, heading, speed, confidence, and
sensor-specific fields (control link, Remote ID, pilot position, blade spin, and so on).
Call this first.
- **Inputs:** `event_id` (e.g. "07"), `up_to_time` ("YYYY-MM-DD HH:MM:SS")
- **Returns:** list of readings (columns as in `events-columns.md`)
- **Source:** `events.csv`

### get_health_status
**Description:** Get the status (operational, degraded, down, unknown) of every sensor and
defeat option at a given time, with the reason and health ID for anything not operational.
Equipment not listed is operational.
- **Inputs:** `time`
- **Returns:** status for each of S-RF, S-RAD, S-ACO, S-GIM, S-WAC, D-JAM, D-INT, D-LAS, D-GUN
- **Source:** `health-status.json`

### get_weather
**Description:** Get the weather and lighting at a given time: visibility, wind, waves,
precipitation, sunrise and sunset, and day/night/twilight. Visibility and wind limit some
defeat options.
- **Inputs:** `time`
- **Returns:** conditions, with any "adjusted" flag
- **Source:** `weather.json`

### get_notices
**Description:** Get the time-based notices in effect at a given time: alert level, the
base's own drone flights, laser satellite-pass windows, airfield status, shipping, shoreline
work, the regatta, and outside-agency contacts. Each notice has an ID (N-xx).
- **Inputs:** `time`
- **Returns:** notices whose time window includes `time`
- **Source:** `roe-notices.md`

### check_site_zone
**Description:** Find which Fort GBUS zone a grid position is in, with its ground-hazard and
backstop ratings. Use it for what lies below a drone or a pilot.
- **Inputs:** `x`, `y` (meters)
- **Returns:** zone ID, name, ground hazard, backstop rating, conditions; distance to the
  nearest critical asset
- **Source:** `site.json`

### check_line_of_fire
**Description:** Calculate the geometry from a defeat option to a target: bearing, elevation
angle, and distance; whether the target is inside the option's allowed sector; and which
zones lie along the line beyond the target. Use it before marking the laser or gun as
allowed.
- **Inputs:** `option_id` (D-LAS, D-GUN, D-JAM, D-INT), `x`, `y`, `altitude`
- **Returns:** bearing, elevation angle, distance, in-sector yes/no, zones crossed beyond
  the target (to the limit of the option's danger range)
- **Source:** `site.json`
- **Why it exists:** language models are unreliable at trigonometry. Doing the geometry in code
  makes the laser elevation limit (ROE-5.7), gun sector (ROE-5.12), and backstop checks
  (ROE-5.11, ROE-5.13) exact.

### search_rules
**Description:** Search the Fort GBUS standing rules of engagement and return the most
relevant rule sections, each with its ID (ROE-x.y). Use it to confirm what a rule says before
citing it.
- **Inputs:** `query` (plain words, e.g. "laser elevation limit")
- **Returns:** top matching rule sections with IDs and full text
- **Source:** `roe-standing.md` (this is the RAG part)

### get_control_room_info — *safety agent only*
**Description:** Get information available only to the control room at a given time: patrol
eyes-on reports, air traffic from the tower, outside-agency reports. Each entry has an ID
(C-xx). This information must never be shown to the operator.
- **Inputs:** `time`
- **Returns:** entries with time at or before `time` for the current event
- **Source:** `control-room-info.json`

---

## Output tools (one per agent; each agent must call its tool exactly once)

These give each agent's answer a fixed structure, so the operator display, the run log, and
the grader can read it reliably.

### submit_assessment — analyst
- `tracks`: for each track: ID, classification (not a drone / friendly / unknown drone),
  position, altitude, heading, speed, sensors reporting, confidence (HIGH / MEDIUM / LOW),
  PID yes/no, PVID yes/no
- `threat_level`: NONE / LOW / MEDIUM / HIGH / CRITICAL, with `indicators_up` and
  `indicators_down`
- `recommended_rung` (0–6) and `recommended_action` (plain words)
- `options`: for each of jammer, interceptor, laser, gun: ALLOWED / BLOCKED / NOT NEEDED,
  with reasons and IDs
- `notifications`: who to notify and why (ROE-6)
- `confidence` and `what_would_change`
- `citations`: every ID relied on

### submit_review — reviewer
- `own_assessment`: brief independent view (track picture, threat level, allowed options)
- `verdict`: APPROVE / REJECT
- `discrepancies`: each difference from the analyst, with the correct fact and ID
- `reasons`: why approved or rejected
- `would_accept`: if rejected, what the reviewer would accept instead
- `notes`: minor issues; any view that a stronger response is justified
- `citations`

### submit_advice — safety agent
- `advice`: CONCUR / CONCUR WITH CAUTIONS / RECOMMEND STOP
- `new_information`: control-room information the operator did not have, with C-xx IDs
- `pvid_status`: for laser or gun: yes/no and source (camera or observer, with time)
- `override_assessment`: if the operator overrode, operator's reason vs. reviewer's reasons
- `concerns` and `safer_alternative`
- `citations`
