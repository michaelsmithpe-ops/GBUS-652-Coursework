# Fort GBUS — Site Description

*Draft 2 (late fall). Entirely fictional. The base, its layout, distances, and equipment positions are
made up for this exercise and do not represent any real location or system.*

## 1. Overview

Fort GBUS is a fictional military installation on the U.S. (south) shore of Lake America.
The lake lies to the **north**; the base and the fictional town of **Harborview** lie to the
south and east. The U.S.–Canada border runs east–west across the lake, along the middle of
the shipping lane.

## 2. Grid

All positions use a local grid in **meters**:

- **Origin (0, 0):** Grid Reference Point GRP-0, a survey marker on the shoreline in front
  of the base.
- **x:** meters **east** (negative = west).
- **y:** meters **north** (positive = over the lake, negative = inland).
- **Bearings:** degrees true, measured clockwise from north (000 = north over the lake,
  090 = east, 180 = south inland, 270 = west).
- **Altitude:** meters above ground / lake level.

Distances are made up and compressed for the scenario (for example, the border is only
5 km offshore, much closer than it would be on the real lake).

## 3. Map

```
 y (m)
                                 (Canadian waters)
  +6000  ─────────────────────────────────────────────────────────────────
                            SHIPPING LANE  (y = +4,000 to +6,000)
  +5000  ═══════════ U.S. / CANADA BORDER (y = +5,000, mid-lane) ════════════
  +4000  ─────────────────────────────────────────────────────────────────

                         OPEN WATER  (Lake America)
                 ↘ airfield approach corridor (from NW, over water)

      0  ~~~~~~~~~~ BEACH ~~~~~~~~~~ ● GRP-0 ~~~~~~~~ MARINA ~~~ FUEL FARM ~~|  HARBORVIEW
         (-2500 to -1000)          shoreline        (+1000..    (+1800..   |  (town, x > +2500)
                                                     +1600)      +2300)    |
   -500                [L]laser  [C]gimbal [R]radar+[J]jammer  [W]wide    |
                                 [G]gun (at shore)                        |
  -1000               acoustic array (x -1000..+1000, y -1000..0)          |
                                     [I] interceptor pad                   |
  -1500                         ★ CONTROL ROOM / HQ                        |
         BASE HOUSING                                                     |
  -2500  (-2200..-800, -2500..-1200)          AIRSTRIP + HELIPAD          |
                                              (+500..+1800, -2600..-2400) |
  -3000  ═══════════════════ PUBLIC ROAD (south boundary) ════════════════╛
        -2500        -1000          0          +1000        +2000   +2500   x (m)
```

## 4. Zones

Each zone has a **ground-hazard** rating (who or what could be hurt by a drone, debris, or a
defeat action over it) and a **backstop** rating (whether it is an acceptable place for
rounds, debris, or a beam to end up).

| ID | Zone | Area (x, y in m) | Normally present | Ground hazard | Backstop |
|---|---|---|---|---|---|
| Z-LAKE | Open water (near shore) | y 0 to +4,000 | A few hardy boaters; no swimmers in late fall | Low (check for boats) | **Preferred** (if clear of boats) |
| Z-SHIP | Shipping lane | y +4,000 to +6,000 (border runs along y +5,000) | Freighters, ferries | High (crewed vessels) | **Never** |
| Z-CAN | Canadian waters | y > +5,000 | Civilian boats | — | **Never** (foreign territory) |
| Z-BEACH | Base beach | x −2,500 to −1,000, y −100 to 0 | Late fall: mostly empty; occasional walkers, dog walkers, or work crews | Low when empty, High when occupied | **Never** when occupied; must be confirmed empty |
| Z-MARINA | Base marina | x +1,000 to +1,600, y −200 to +300 | Most boats hauled out; a few hardy boaters and crews | Medium | **Never** |
| Z-FUEL | Fuel farm (tanks + offload pier) | x +1,800 to +2,300, y −900 to −500 | Few workers; large fuel quantities | **Critical** (fire/explosion) | **Never** |
| Z-HOUSE | Base housing | x −2,200 to −800, y −2,500 to −1,200 | Families, schools, playgrounds | **Critical** (people) | **Never** |
| Z-HQ | Headquarters / control room | around (0, −1,500) | Staff | High | **Never** |
| Z-AIR | Airstrip + helipad | x +500 to +1,800, y −2,600 to −2,400 | Aircraft, crews | High | **Never** |
| Z-APPR | Airfield approach corridor | Over water from the NW toward Z-AIR | Arriving / departing aircraft | High (aircraft) | **Never** when aircraft active |
| Z-TOWN | Harborview (civilian town) | x > +2,500 | Public | **Critical** (civilians) | **Never** |
| Z-ROAD | Public road (south boundary) | y ≈ −3,000 | Public traffic | High | **Never** |
| Z-OPEN | Open base land (fields, shoreline strip) | Remaining base area | Occasional patrols | Low | Conditional (check for people) |

## 5. Sensor positions

| ID | Sensor | Position (x, y) | Height | Notes |
|---|---|---|---|---|
| S-RF1 | RF detection node (west) | (−2,000, −200) | 15 m mast | Three RF nodes together can estimate a pilot's position |
| S-RF2 | RF detection node (center) | (0, −1,500) | 20 m mast (HQ roof) | |
| S-RF3 | RF detection node (east) | (+2,000, −300) | 15 m mast | |
| S-RAD | Radar | (0, −300) | 25 m tower | Looks mainly over the lake; sea clutter in high waves |
| S-ACO | Distributed acoustic array | 12 nodes spread over x −1,000 to +1,000, y −1,000 to 0 (~2 km²) | Ground level | Best inside its footprint; weaker over open water |
| S-GIM | Gimbal camera (IR / visible / high-speed) | (−200, −250) | 20 m tower | Must be pointed (cued) by another sensor |
| S-WAC | Wide-area scanning camera | (+300, −350) | 20 m tower | Continuous sky scan; detects but does not identify |

## 6. Defeat-option positions

| ID | Option | Position (x, y) | Notes |
|---|---|---|---|
| D-JAM | RF jammer | (0, −300) | Shares the radar tower; affects an area, not just the target |
| D-INT | Interceptor drone pad | (+600, −800) | Launches and recovers on base |
| D-LAS | Laser on remote gimbal | (−400, −200) | Elevation-angle limit and other rules are set in `roe-standing.md` |
| D-GUN | Gun on remote gimbal | (+200, −100) | Sited at the shoreline so it normally fires out over the lake |

## 7. Lines of fire and backstops (physical layout only)

These are the physical facts the safety checks need. The actual rules (what is allowed,
when, and with whose approval) live in `roe-standing.md` and `roe-notices.md`.

- **Toward the lake (roughly bearings 300–060 from the shoreline sites):** open water is the
  preferred backstop, **if** no boats or swimmers are in the path and the shipping lane and
  Canadian waters are beyond the reach of rounds or debris.
- **Toward the east (roughly 060–120):** the marina, fuel farm, and Harborview lie in this
  direction. Never an acceptable backstop.
- **Toward the south (roughly 120–240):** HQ, housing, airstrip, and the public road. Never
  an acceptable backstop.
- **Toward the west (roughly 240–300):** the beach, then open base land. Acceptable only if
  the beach is confirmed empty.
- **Upward:** for the laser, steep angles are limited (satellite protection) and the
  airfield approach corridor must be clear.

## 8. Season and scheduled activity

The event week is **Monday, November 30 – Saturday, December 5, 2026** (late fall).

- **Daylight:** short days. Sunrise about 07:30, sunset about 16:35. The low sun causes glare
  off the water much of the day; dawn and dusk bring thermal crossover that weakens IR.
- **Lake conditions:** lake-effect snow, gales, fog, cold water, and high waves (radar sea
  clutter) are all common.
- **Beach:** no swimmers. Occasional walkers, dog walkers, or shoreline work crews; must still
  be confirmed empty before it can serve as a backstop.
- **Marina / boating:** most boats are hauled out; a few hardy boaters still go out. A
  **"frostbite" regatta** (cold-weather sailing race) is held offshore on Saturday.
- **Airstrip / helipad:** scheduled flights; the base also flies its own drones for
  inspection and training.
- **Shipping lane:** still active; the last freighters of the season run before ice forms.

**Weather source:** conditions in `weather.json` start from the public U.S. National Weather
Service forecast (or observations) for **Rochester, NY**, used as the reference station for
fictional Fort GBUS. Where an event needs different conditions, the change is marked as
adjusted.
