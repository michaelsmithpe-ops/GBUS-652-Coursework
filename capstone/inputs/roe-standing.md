# Fort GBUS Counter-Drone Standing Rules of Engagement

*Draft 1. Entirely fictional. These rules are made up for a course exercise. They are not
real rules of engagement for any installation and are not legal advice. The public-law
summaries in Section 1 are simplified, high-level descriptions only.*

Every rule has an ID (for example **ROE-4.2**). Recommendations, reviews, and safety advice
**must cite the rule IDs they rely on.** Time-based notices are in `roe-notices.md`
(IDs **N-xx**); equipment status is in `health-status.json` (IDs **H-xx**).

---

## 1. Authority and principles

**ROE-1.1 Public law (summary).** Federal law (10 U.S.C. § 130i) allows the Department of
Defense to take action against drones that threaten certain covered military facilities.
Allowed actions include detecting, identifying, tracking, and warning; disrupting the
drone's control link; taking control of or seizing the drone; and, where necessary, using
reasonable force to disable or destroy it. Fort GBUS is treated as a covered facility for
this exercise.

**ROE-1.2 Human judgment (summary).** DoD policy (DoD Directive 3000.09) requires that
systems be designed so commanders and operators exercise appropriate human judgment over the
use of force. At Fort GBUS, **software recommends; humans decide.** No defeat option is ever
triggered automatically.

**ROE-1.3 Remote ID (summary).** FAA rules require most drones flying in U.S. airspace to
broadcast Remote ID (identity and location). A drone with no Remote ID is not proof of
hostile intent, but it is an indicator (ROE-3.2).

**ROE-1.4 Satellite protection (summary).** Lasers aimed into the sky can damage satellites.
DoD coordinates laser use through a laser clearinghouse that issues predictive-avoidance
windows when firing is not allowed. Fort GBUS windows are published in `roe-notices.md`.

**ROE-1.5 Least force that works.** Always use the lowest rung on the escalation ladder
(Section 4) that is likely to resolve the threat. Step up only when lower rungs have failed,
are unavailable, or cannot act in time.

**ROE-1.6 Silence means no.** If a required approval is not given in time, the action is
not taken. The default is always the safe choice.

**ROE-1.7 Safety over mission.** If a defeat option cannot be used without unacceptable
risk to people, vessels, or aircraft, it is blocked, even if the drone gets through. Report
and track instead.

**ROE-1.8 Accountability.** The control room, meaning the person in charge of the watch, is
the final authority for this process and is responsible for every action taken through it.
Agents and software only advise; responsibility can never be handed to a tool. Every
recommendation, review, decision, override, and stop is logged so that each action can be
traced to the person who approved it.

**ROE-1.9 Layered safety.** Every proposed action passes through five independent checks in
order: analyst agent, reviewer agent, human operator, safety agent, and control room. Each
check fails safe: a reviewer rejection becomes DO NOT ENGAGE (ROE-4.2), an override still
needs higher approval (ROE-4.3), a safety-agent failure never blocks or approves anything
(ROE-4.5), and silence from the control room means no (ROE-1.6).

---

## 2. Definitions

**ROE-2.1 Track.** A single object followed over time, built from one or more sensors.

**ROE-2.2 Identifying sensor.** A sensor that can tell what an object is: RF (protocol,
Remote ID), gimbal camera (visual ID, blade spin). Radar, the wide-area camera, and the
acoustic array **detect and locate** but do not identify on their own.

**ROE-2.3 Positive identification (PID).** A track has PID as a drone when **both** are
true:
- at least **two independent sensors** report it, with positions agreeing within **200 m**;
- at least **one identifying sensor** confirms it is a drone (e.g., a control link, or
  blade spin seen).

**ROE-2.4 Positive visual identification (PVID).** A track has PVID when **all** are true:
- the target is **in view** of the gimbal camera (visible, IR, or high-speed channel) or of
  a trained human observer with eyes on it (for example, a security patrol);
- the image or report **confirms it is a drone** (for example, rotors or blade spin seen,
  airframe visible), not a bird, aircraft, or other object;
- the image or report is **current** (no older than **30 seconds**) and its position
  **matches the track** being engaged.

PVID is stronger than PID (ROE-2.3): PID can come from RF and radar alone, but PVID requires
eyes on the target. PVID is lost when the target leaves view, the image is no longer
current, or visibility no longer allows confirmation.

**ROE-2.5 Sensor disagreement.** If two detecting sensors report the same track more than
**200 m apart**, and the difference is not explained (for example by a sensor marked
degraded in `health-status.json`), track confidence is **LOW** until resolved.

**ROE-2.6 Friendly drone.** A drone whose Remote ID **and** time and route match an
own-flight entry in `roe-notices.md`.

**ROE-2.7 Critical asset.** The fuel farm (Z-FUEL), headquarters / control room (Z-HQ),
base housing (Z-HOUSE), and the airstrip / helipad (Z-AIR). See `site.md`.

---

## 3. Threat assessment

**ROE-3.1 Threat levels.**

| Level | Meaning |
|---|---|
| NONE | Not a drone (e.g., birds), or a friendly drone (ROE-2.6) |
| LOW | Drone with no threatening indicators; e.g., hobbyist away from critical assets |
| MEDIUM | Drone with one or two threat indicators |
| HIGH | Drone with several threat indicators, or heading toward a critical asset |
| CRITICAL | Drone about to reach a critical asset, or a hostile act in progress |

**ROE-3.2 Threat indicators.** Raise the level for each that applies:
- no Remote ID;
- no RF emissions while flying (pre-programmed / autonomous flight);
- encrypted or unknown control protocol;
- payload seen, or unknown object carried;
- flight toward, over, or loitering near a critical asset (ROE-2.7);
- camera pointed at the base; repeated passes;
- launch or control from off base, a vessel, or across the border;
- larger drone class (Group 2 or above).

**ROE-3.3 Lowering indicators.** Lower the level for: valid Remote ID; pilot located in
plain view and not concealing themselves; flight away from critical assets; matching a
published activity (e.g., a regatta filming drone broadcasting Remote ID).

**ROE-3.4 Low confidence.** If track confidence is LOW (ROE-2.5) or there is no PID
(ROE-2.3), no action above **rung 2** may be recommended unless the threat is CRITICAL.

---

## 4. Escalation ladder and approvals

**ROE-4.1 Ladder.**

| Rung | Action | Minimum threat level | Approval needed |
|---|---|---|---|
| 0 | Monitor / track | Any | Automatic |
| 1 | Point camera, identify, alert | Any | Automatic |
| 2 | Warn; send security to pilot; notify outside agencies (ROE-6) | LOW | Operator |
| 3 | RF jammer | MEDIUM | Operator + control room |
| 4 | Interceptor drone | HIGH | Control room |
| 5 | Laser | HIGH | Control room |
| 6 | Gun | CRITICAL | Control room |

**ROE-4.2 Reviewer.** Every recommendation from the analyst is checked by an independent
reviewer before it reaches the operator. If the reviewer rejects it, the recommendation to
the operator becomes **DO NOT ENGAGE**, shown with the reviewer's reasons and the analyst's
original proposal.

**ROE-4.3 Operator override.** The operator may override a DO NOT ENGAGE recommendation
only deliberately, using the override control, and must give a written reason. The override
only sends the request up the chain; it never skips a rung's approval (ROE-4.1).

**ROE-4.4 Control room authority.** The control room has final say. It may **stop** any
engagement, especially when it has better information (eyes on the target area, aircraft
inbound, people in the backstop). It may not step up an engagement the operator rejected.

**ROE-4.5 Safety agent.** The safety agent sits between the operator and the control room.
It reviews the operator's decision (including any override and its reason) and adds its
advice. It **advises only**: it never approves, blocks, or changes anything, and everything
the operator sent passes through to the control room unchanged.
- **Advice goes forward only.** The safety agent may use control-room-only information, so
  its advice goes to the control room only, never back to the operator.
- **Failure passes through.** If the safety agent fails or does not respond in time, the
  operator's request still goes to the control room, marked **NO SAFETY ADVICE AVAILABLE**.
  It still needs control-room approval.

**ROE-4.6 Multiple tracks.** Handle the highest threat first. Among equal threats, handle the
one with the shortest time to reach a critical asset first. Keep tracking all others.

**ROE-4.7 PVID required for laser and gun.** The control room must have **positive visual
identification** (ROE-2.4) of the target **before** approving the laser (rung 5) or the gun
(rung 6), and must **keep PVID for the whole engagement**. The camera image or observer
report must be available in the control room. If PVID is lost at any point, the laser or
gun engagement **stops immediately** and may resume only when PVID is regained and the
control room approves again. Without PVID, the laser and gun are blocked.

---

## 5. Defeat-option rules

A defeat option is **blocked** if **any** of its rules below is broken, **or** if it is
**down** in `health-status.json` (ROE-7.1).

### RF jammer (D-JAM)

**ROE-5.1** Only effective when the drone has a **live control link** (RF sensor reports a
control link). Never recommend the jammer against an RF-silent drone.

**ROE-5.2** Not allowed when a **crewed aircraft** is within **3 km** of the target, or when
a vessel in the shipping lane is within **2 km** of the target (risk of interference with
navigation and radio).

**ROE-5.3** Consider what the drone may do when its link is lost (hover, land, return to the
pilot, or continue on its own). Over a critical asset or people, a drone that lands or falls
there is a hazard. Pair jamming with sending security to the pilot location if known.

### Interceptor drone (D-INT)

**ROE-5.4** Not allowed when a **crewed aircraft** is within **3 km** of the target or the
interceptor's flight path, unless the control room confirms deconfliction.

**ROE-5.5** Over a zone with **Critical** ground hazard (`site.md`), allowed only when the
threat is **HIGH or CRITICAL** (falling debris).

**ROE-5.6** Not allowed when sustained wind is above **15 m/s** (from the weather file).

### Laser (D-LAS)

**ROE-5.7 Elevation limit.** Not allowed when the target is more than **45 degrees above
the horizon** as seen from the laser site (satellite protection).

**ROE-5.8 Satellite windows.** Not allowed during any predictive-avoidance window in
`roe-notices.md`.

**ROE-5.9 Aircraft.** Not allowed when a crewed aircraft is within **5 km** of the beam path,
or when the airfield approach corridor is in use.

**ROE-5.10 Visibility.** Not allowed when visibility is below **3 km** (fog, snow, haze,
heavy spray), or when the gimbal camera cannot hold the target in view. The control room
must also have PVID throughout (ROE-4.7).

**ROE-5.11 Beam path.** The beam path past the target must not cross people, vessels, the
shipping lane, Canadian waters, or any zone whose backstop rating is **Never** (`site.md`).

### Gun (D-GUN)

**ROE-5.12 Sector.** Allowed only within the firing sector **bearing 300 through 060**
(over the lake) from the gun site, and at elevations between **5 and 30 degrees**. Steeper
fire risks rounds falling back on the base.

**ROE-5.13 Backstop.** Rounds and debris must fall into open water rated **Preferred** in
`site.md`, with **no vessels** within **3.5 km** along the line of fire. Never toward the
shipping lane, Canadian waters, the marina, the fuel farm, Harborview, housing, the beach
when occupied, or any area with people.

**ROE-5.14 Last resort.** Only at threat level **CRITICAL**, only with control-room
approval, and only when the jammer, interceptor, and laser are blocked
or unavailable. The control room must have PVID throughout (ROE-4.7).

---

## 6. Non-defeat responses and notifications (rung 2)

**ROE-6.1 Pilot on base.** Send base security to detain and question the pilot and have the
drone landed. This is often the most effective response.

**ROE-6.2 Pilot off base, on U.S. land.** Notify civilian law enforcement (Harborview Police
Department). Base security does not pursue off base.

**ROE-6.3 Pilot on the water, U.S. side.** Notify the U.S. Coast Guard.

**ROE-6.4 Pilot across the border.** Notify the U.S. Coast Guard, which coordinates with
Canadian authorities. **Never** pursue, jam toward, or fire toward Canadian waters.

**ROE-6.5 Pilot unknown.** Keep tracking; notify base security and the control room; watch
for the drone's return path, which may lead to the pilot.

---

## 7. Equipment health and weather

**ROE-7.1 Down equipment.** Never use data from, or recommend, equipment that is **down**
in `health-status.json` at the time of the reading.

**ROE-7.2 Degraded equipment.** Data from **degraded** sensors carries lower confidence;
do not let a degraded sensor alone decide PID or position.

**ROE-7.3 Unknown status.** Treat equipment with **unknown** status as unavailable for
defeat, and its data as unreliable.

**ROE-7.4 Status changes during an event.** Check status at **each step**. If a defeat
option fails during an event, re-plan with the remaining options.

**ROE-7.5 Weather.** Use the weather file for the event time. Fog, snow, and haze reduce
camera and laser use (ROE-5.10); high waves increase radar sea clutter; high wind limits
the interceptor (ROE-5.6).

---

## 8. Friendly drones and scheduled activity

**ROE-8.1 Friendly drones.** A drone that meets ROE-2.6 is threat level NONE. No defeat
action. If it leaves its published route, contact airfield operations before any action.

**ROE-8.2 Published activities.** Check `roe-notices.md` for events (regattas, work crews,
flights) that put people, vessels, or aircraft in the area. These may block defeat options
(Section 5) and may explain a drone's presence (ROE-3.3).

---

## 9. What every recommendation must include

**ROE-9.1** Every analyst recommendation, reviewer verdict, and safety-agent advice must
state:
1. the track(s) and their classification, position, and confidence;
2. the threat level and the indicators behind it (ROE-3);
3. the recommended rung and action;
4. each defeat option that is **blocked**, with the reason and rule ID;
5. the notifications to make (ROE-6);
6. the rule, notice, and health IDs relied on.
