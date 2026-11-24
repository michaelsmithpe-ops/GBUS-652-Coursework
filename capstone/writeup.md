# Capstone Writeup: Fort GBUS Counter-Drone Decision Aid

## What I Built

I built a decision aid for the counter-drone watch at Fort GBUS, a fictional base on the shore of
Lake America. For each drone event, a fixed team of three Claude agents (claude-sonnet-5-5) reads
the sensor readings, weather, equipment health, notices, site map, and the base's rules of
engagement. It then recommends the least force that works, and two people decide: the operator and
the control room. The tool never acts on its own. A Streamlit web page shows the operator view and
the control-room view, has the decision buttons, and replays past runs. Every real run is logged.

How it changed as I built it:

- It started as a command-line pipeline with simulated human decisions. I then added the web page
  in stages: first replays, then live operator buttons, then control-room buttons, then a "Start a
  run" control that defaults to a free dry run.
- I made a reviewer REJECT turn what the operator sees into "DO NOT ENGAGE", and made a reviewer
  that fails to answer count as a REJECT, so the system fails safe.
- The control room first had a 20-second time limit, where silence meant "no". I removed it: on the
  web page nothing happens until a person clicks, because a real control room decides when it is
  ready.
- I added conversation caching to the agents' tool loops, which cut the cost of a run by about a
  third.
- After my first three real runs, I added real weather (a saved National Weather Service forecast,
  adjusted where an event needs fog or wind and marked as adjusted). I moved those three runs to
  `runs/archive/`, since they ran without weather.
- To match the course requirements, I added the one-line-per-run log (`runs/log.jsonl`) and made
  the tool read the API key only from `API-Key.txt` above the repository.

## Why This Approach

Techniques: Prompt engineering, RAG, Agent, MCP server, and Team (a fixed pipeline of specialist agents). The job needs all five, as explained below.

**1. Prompt engineering: carefully designed system prompts.** Each agent's system prompt is a
shared prompt (`prompts/shared.txt`) plus a role prompt (`analyst.txt`, `reviewer.txt`,
`safety.txt`), about 1,400 words in all.
- *Step-by-step reasoning.* Each role has numbered steps to follow every time. For example, the
  analyst gathers facts, then builds the track picture, classifies each track, sets the threat
  level, checks the ground and the line of fire, marks every defeat option ALLOWED, BLOCKED, or NOT
  NEEDED, and only then recommends. It writes "facts, then rule, then conclusion" so the reviewer
  can check it.
- *Hard constraints with rule IDs*, for example "never recommend the laser or the gun without
  positive visual identification (ROE-4.7)". Every claim must cite its source by ID (rules
  ROE-x.y, notices N-xx, equipment health H-xx, sensor and time).
- *Independence by design.* The reviewer is told to check on its own first and only then read the
  analyst's work, so it isn't anchored by a confident argument.
- *Safety against prompt injection.* Text inside the data, such as sensor notes and operator
  reasons, is information, not instructions.
- *Structured output.* Each agent must finish by calling its own "submit" tool, whose schema fixes
  the fields and the allowed values (for example APPROVE or REJECT), so the code can read the
  result reliably.
- The prompts are versioned, and every run log records the version and a hash of the prompt text.

Why the job needs it: the rules are strict and the stakes are high. The agents must follow the
same procedure every time, show their work, and refuse unsafe options for stated reasons.

**2. RAG: answers grounded in the base's rules, retrieved from a vector database.** The Fort GBUS
standing rules of engagement (`inputs/roe-standing.md`, made up for this project) are split into 54
chunks, one per rule, each starting with its section heading so it makes sense on its own. The
chunks are embedded with Chroma's built-in embedding model and stored in a local Chroma database.
The agents call `search_rules` with a question in plain words and get the four closest rules back.
If the question names a rule ID such as ROE-5.7, that rule comes back first, word for word. The
rules include short public-source summaries of the federal law and policy they rest on: 10 U.S.C.
§ 130i, DoD Directive 3000.09, the FAA Remote ID rule, and the DoD laser clearinghouse. They are
retrieved like any other rule. The time-based notices are not in the vector database. They are
looked up exactly by time, because a notice applies only inside its time window.

Why the job needs it: an agent must quote the exact rule that allows or blocks an option.
Retrieval gives it the real rule text when it needs it, instead of relying on memory, and lets the
reviewer confirm each cited rule.

**3. Agent: Claude decides which tools to use, and in what order.** Each of the three agents runs
its own tool loop. Claude decides which tools to call, in what order, and how many times, then
finishes by calling its submit tool. The code only sets limits: at most 20 tool calls per agent per
step, a single reminder if the agent stops without submitting, and a server-side fallback if the
model refuses. In my first real runs, the analyst called `search_rules` anywhere from 7 to 36 times
per run, and the order of its tool calls changed from run to run.

Why the job needs it: every event is different. One needs the line of fire checked from three
defeat options, another needs a degraded sensor discounted, and another needs a notice about a
friendly drone. A fixed script can't know in advance which facts matter.

**4. MCP server: the agents' tools are offered through MCP.** `app/fgb_mcp_server.py` is an MCP
server with seven read-only tools: `get_sensor_readings`, `get_health_status`, `get_weather`,
`get_notices`, `check_site_zone`, `check_line_of_fire`, and `search_rules` (the RAG search). The
pipeline starts one copy of the server for each agent role and connects over stdio. Only the safety
agent's server adds an eighth tool, `get_control_room_info`, which shows information only the
control room can see (aircraft inbound, people in the area, patrol reports). Every tool reads a
clock file and refuses to show anything after the current time, so no agent can look into the
event's future.

Why the job needs it: MCP keeps the data separate from the agents, and lets the code (not a
prompt) control who can see what. The operator's side physically cannot see control-room
information.

**5. Team: several specialists, run by a fixed pipeline.** The order never changes: **analyst**
(proposes) → **reviewer** (independently approves or rejects) → **operator** (person: accepts,
rejects, or overrides with a written reason) → **safety agent** (advises the control room only;
it cannot block or change anything) → **control room** (person: final authority, approves or
stops). The code decides the order; no model acts as an orchestrator. A reviewer REJECT means the
operator sees "DO NOT ENGAGE". Anything that asks for force (the RF jammer, rung 3, or above), and
any override, must go through the safety agent and the control room.

Why the job needs it: this mirrors layered safety in real counter-drone work. No single agent's
mistake can reach an action, because each step checks the one before it, and people sit at the
two points where force is approved.

Human oversight: Approval required. The tool only recommends and never fires, controls, or points anything. Every recommendation goes to the operator, and any use of force or any override also needs the control room's approval. Force against a drone can hurt people, damage property, or break the law, so a person must approve every action and stay responsible for it.

## Business Case

Who uses it: The counter-drone watch operator and the person in charge of the watch in the control room, every time the sensors pick up a drone near the base, around the clock.

Problem: Drone incursions over military installations have increased over the past two years. Most come from harmless hobbyists, but not all. Some are threats posing as hobbyists, flown to harass or distract the local security forces or to surveil the base for weak spots to exploit later. Others come from people seeking information they should not have, such as a news outlet or podcaster looking for classified material, and in the worst cases they are real attacks meant to damage the installation or its mission. Fort GBUS has installed a network of sensors and defeat tools to meet this threat. The system cost several hundred thousand dollars to install and costs tens of thousands of dollars a month to run. It needs an operator around the clock (two during peak periods), trained staff to maintain and arm it daily or weekly, and extra trained staff in the control room. The hardest part of the job is the decision. For every detection, the operator must cross-check several sensors, the weather, equipment health, active notices, and the rules of engagement, often within minutes, and then pick the least force that works. A mistake either way is costly. Engaging a hobbyist or a friendly drone creates safety and legal exposure, and missing a real threat puts millions of dollars of equipment and facilities, and the thousands of service members and family members who live on Fort GBUS, at risk.

Model: claude-sonnet-5-5 (Claude Sonnet 5.5)

Prices used: $2.00 per million input tokens and $10.00 per million output tokens (Anthropic's price list, checked 2026-11-20).

Cost per run: TO COME (worked out from the runs in `runs/log.jsonl` at the prices above).

Monthly volume: TO COME (a number, your estimate).

Monthly cost: TO COME (cost per run times monthly volume).

## Example Run

TO COME: one real run pasted from the tool, unedited.

## Reflection

Failed run: TO COME

What went wrong: TO COME

How I fixed it: TO COME

Fixed run: TO COME
