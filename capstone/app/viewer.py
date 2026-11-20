"""Fort GBUS operator display - Phase A viewer (no API calls).

Run (from the repository folder, GBUS-652-Coursework):
    .venv\\Scripts\\python.exe -m streamlit run capstone\\app\\viewer.py

What it shows, for any event and any moment in it:
  - header: event, time, weather, notices in effect
  - map of Fort GBUS with each sensor's reports up to that moment, the track, and the pilot
  - system status board: every sensor and defeat option, green / yellow / red
  - latest sensor readings
  - replay of a saved run (read from runs/<run-id>/detail.jsonl): what the agents and people
    decided at that step. The Operator view never shows control-room-only information;
    the Control-room view adds it, plus the safety advice.
  - Phase B, LIVE runs (pipeline.py --web): the page finds a run in progress, follows its event
    and time, and shows decision buttons when the pipeline asks (runs/<id>/pending.json).
    A click writes runs/<id>/answer.json. Operator: Approve / Reject, and when the reviewer
    said DO NOT ENGAGE, a separate OVERRIDE button that will not send without a written reason.
    The Operator view never shows a control-room request (it carries the safety advice).
    Control room: Approve, or STOP with a required reason. No time limit: nothing is carried
    out until the control room approves. The safety agent's call is shown in bold next to the buttons.
Everything is read from the input files and run logs; nothing calls Claude.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

import fgb_data as D                      # noqa: E402
from site_map import build_site_figure    # noqa: E402

RUNS = Path(os.environ.get("FGB_RUNS_DIR") or ROOT / "runs")   # tests point this at a temp folder
LIVE_LOG_STALE_S = 600      # a run whose log has not changed for 10 min (and no request) is not live
PENDING_STALE_S = 15        # the pipeline touches pending.json every 0.5 s while it waits
MILESTONES = {"step_start", "agent_submit", "shown_to_operator", "operator_decision",
              "web_request", "control_room_decision", "step_end", "run_end"}
SENSOR_STYLE = {   # how each sensor's reports are drawn
    "S-RAD": ("Radar", "circle", "#1f6feb"),
    "S-RF": ("RF", "diamond-open", "#8250df"),
    "S-ACO": ("Acoustic", "x", "#bf8700"),
    "S-GIM": ("Gimbal camera", "star", "#1a7f37"),
    "S-WAC": ("Wide-area camera", "square-open", "#57606a"),
}
STATUS_COLOR = {"operational": "#1a7f37", "degraded": "#bf8700", "down": "#cf222e", "unknown": "#6e7781"}
EQUIP_NAMES = {"S-RF": "RF detection", "S-RAD": "Radar", "S-ACO": "Acoustic array",
               "S-GIM": "Gimbal camera", "S-WAC": "Wide-area camera", "D-JAM": "RF jammer",
               "D-INT": "Interceptor", "D-LAS": "Laser", "D-GUN": "Gun"}

st.set_page_config(page_title="Fort GBUS Counter-Drone", layout="wide")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@st.cache_data
def load_events() -> dict[str, list[dict]]:
    with open(ROOT / "inputs" / "events.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["Event ID"], []).append(r)
    return out


@st.cache_data
def load_site() -> dict:
    return D.load_site()


def runs_for(event_id: str, include_dry: bool = False, extra: str | None = None) -> list[str]:
    """Saved runs for an event, oldest first. `extra`: a run that just finished (the pipeline
    writes its index row a moment after the log ends, so it may not be listed yet)."""
    path = RUNS / "run-index.csv"
    out: list[str] = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            out = [r["run_id"] for r in csv.DictReader(f)
                   # spreadsheet programs may re-save False as FALSE and 07 as 7
                   if r["event"].strip().zfill(2) == event_id
                   and (include_dry or r["dry_run"].strip().lower() == "false")
                   and (RUNS / r["run_id"]).exists()]
    if extra and extra not in out and (RUNS / extra).exists():
        out.append(extra)
    return out


def last_step_time(run_id: str) -> str | None:
    """The time of the last step a run reached (from its log)."""
    try:
        lines = (RUNS / run_id / "detail.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    starts = [json.loads(l)["now"] for l in lines if '"step_start"' in l]
    return starts[-1] if starts else None


def run_step(run_id: str, now: str) -> dict | None:
    """Everything logged for the step at time `now` in a saved run, or None."""
    step, out = None, {}
    for line in (RUNS / run_id / "detail.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["kind"] == "step_start":
            step = r["step"] if r["now"] == now else None
            if step is not None:
                out["step"] = step
        elif step is not None and r.get("step") == step:
            if r["kind"] == "agent_submit":
                out[r["role"]] = r["output"]
            elif r["kind"] in ("shown_to_operator", "operator_decision", "control_room_decision", "step_end"):
                out[r["kind"]] = r
    return out or None


@st.cache_data
def load_ladder() -> dict[int, dict]:
    """Rung meanings, read from the ROE-4.1 table in inputs/roe-standing.md (one source of truth)."""
    text = (ROOT / "inputs" / "roe-standing.md").read_text(encoding="utf-8")
    out: dict[int, dict] = {}
    for line in text.split("**ROE-4.1 Ladder.**", 1)[1].splitlines():
        if out and not line.startswith("|"):
            break                                     # end of the table
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0].isdigit():
            out[int(cells[0])] = {"action": cells[1], "min_threat": cells[2], "approval": cells[3]}
    return out


def rung_label(n) -> str:
    """'RUNG 2 — Warn; send security to pilot; ...' (or just 'RUNG n' if unknown)."""
    m = load_ladder().get(n) if isinstance(n, int) else None
    return f"RUNG {n} — {m['action']}" if m else f"RUNG {n}"


def sensor_identity(rows: list[dict], now: str, track_id: str | None) -> list[str]:
    """What the SENSORS report about a track up to `now` (latest value per sensor), as short parts.
    Disagreements stay visible: e.g. 'Group 1 RW (S-RF, S-GIM); Group 2 RW (S-ACO)'."""
    seen = [r for r in rows if r["Timestamp"] <= now and r["Detection (Y/N)"] == "Y"]
    if track_id and any(r["Track ID"] == track_id for r in seen):
        seen = [r for r in seen if r["Track ID"] == track_id]
    seen.sort(key=lambda r: r["Timestamp"])

    def latest(col: str) -> dict[str, list[str]]:
        per_sensor = {}
        for r in seen:
            if r[col]:
                per_sensor[r["Sensor ID"]] = r[col]
        groups: dict[str, list[str]] = {}
        for sid, v in per_sensor.items():
            groups.setdefault(v, []).append(sid)
        return groups

    parts = []
    for col, name in (("Drone class", "class"), ("Radar size class", "radar size"),
                      ("Protocol family", "protocol"), ("Remote ID", "Remote ID")):
        g = latest(col)
        if g:
            parts.append(f"{name} " + "; ".join(f"**{v}** ({', '.join(s)})" for v, s in g.items()))
    return parts


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def find_live() -> dict | None:
    """The newest run still in progress, or None. Looks at the 5 newest run folders."""
    if not RUNS.exists():
        return None
    dirs = sorted((d for d in RUNS.iterdir() if (d / "detail.jsonl").exists()), key=lambda d: d.name, reverse=True)
    for d in dirs[:5]:
        pend_path = d / "pending.json"
        try:
            pend_age = time.time() - pend_path.stat().st_mtime
        except OSError:
            pend_age = None
        if time.time() - (d / "detail.jsonl").stat().st_mtime > LIVE_LOG_STALE_S and (
                pend_age is None or pend_age > PENDING_STALE_S):
            continue
        rows = []
        for line in (d / "detail.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass                                  # a line being written right now
        if not rows or rows[0]["kind"] != "run_start" or rows[-1]["kind"] == "run_end":
            continue
        starts = [r for r in rows if r["kind"] == "step_start"]
        pending = read_json(pend_path) if pend_age is not None and pend_age <= PENDING_STALE_S else None
        return {"run_id": d.name, "dir": d, "event": rows[0]["event"], "dry_run": rows[0].get("dry_run"),
                "humans": rows[0].get("humans", "simulated"),
                "step": starts[-1]["step"] if starts else None, "now": starts[-1]["now"] if starts else None,
                "pending": pending, "stale_request": pend_age is not None and pend_age > PENDING_STALE_S,
                "milestones": sum(r["kind"] in MILESTONES for r in rows)}
    return None


def live_signature(live: dict | None) -> tuple | None:
    if not live:
        return None
    return (live["run_id"], live["step"], (live["pending"] or {}).get("id"), live["milestones"],
            live["stale_request"])


def send_answer(live: dict, answer: dict) -> None:
    """Write answer.json for the pipeline (temp file + replace, so it never reads half a file)."""
    tmp = live["dir"] / "answer.json.tmp"
    tmp.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, live["dir"] / "answer.json")
    st.session_state["sent"] = answer["id"]
    st.rerun()


def num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def event_map(rows: list[dict], now: str, zoom: bool) -> go.Figure:
    fig = build_site_figure(load_site(), show_sectors=True)
    seen = [r for r in rows if r["Timestamp"] <= now and r["Detection (Y/N)"] == "Y"]

    for sid, (name, symbol, color) in SENSOR_STYLE.items():
        pts = [r for r in seen if r["Sensor ID"] == sid and num(r["X (m)"]) is not None]
        if not pts:
            continue
        latest = max(p["Timestamp"] for p in pts)
        fig.add_trace(go.Scatter(
            x=[num(p["X (m)"]) for p in pts], y=[num(p["Y (m)"]) for p in pts], mode="markers",
            name=f"{name} ({sid})",
            marker=dict(symbol=symbol, color=color, line=dict(color=color, width=1.5),
                        size=[13 if p["Timestamp"] == latest else 7 for p in pts],
                        opacity=[1.0 if p["Timestamp"] == latest else 0.35 for p in pts]),
            hovertext=[f"{sid} {p['Track ID']} @ {p['Timestamp'][11:]}<br>({p['X (m)']}, {p['Y (m)']}) "
                       f"alt {p['Altitude (m)']} m, conf {p['Confidence (0-1)']}<br>{p['Sensor note']}"
                       for p in pts], hoverinfo="text"))

    # Track line from radar reports, one per track.
    for tid in sorted({r["Track ID"] for r in seen if r["Track ID"]}):
        rad = sorted((r for r in seen if r["Sensor ID"] == "S-RAD" and r["Track ID"] == tid),
                     key=lambda r: r["Timestamp"])
        if len(rad) >= 1:
            fig.add_trace(go.Scatter(
                x=[num(r["X (m)"]) for r in rad], y=[num(r["Y (m)"]) for r in rad],
                mode="lines+text", line=dict(color="#cf222e", width=3),
                text=[""] * (len(rad) - 1) + [f"  {tid}"], textposition="middle right",
                textfont=dict(size=14, color="#cf222e"), name=f"Track {tid} (radar)", hoverinfo="name"))

    # Pilot estimates (RF).
    pilots = [r for r in seen if r["Sensor ID"] == "S-RF" and r["Pilot located (Y/N)"] == "Y"]
    if pilots:
        p = max(pilots, key=lambda r: r["Timestamp"])
        fig.add_trace(go.Scatter(
            x=[num(p["Pilot X (m)"])], y=[num(p["Pilot Y (m)"])], mode="markers+text",
            marker=dict(symbol="circle-open", size=22, color="#8250df", line=dict(width=3)),
            text=["  PILOT"], textposition="middle right", textfont=dict(color="#8250df", size=13),
            name="Pilot estimate (RF)",
            hovertext=f"Pilot estimate ({p['Pilot X (m)']}, {p['Pilot Y (m)']}) ± {p['Pilot position error (m)']} m",
            hoverinfo="text"))

    if zoom and seen:
        xs = [num(r["X (m)"]) for r in seen if num(r["X (m)"]) is not None]
        ys = [num(r["Y (m)"]) for r in seen if num(r["Y (m)"]) is not None]
        xs += [0]; ys += [0]                      # keep the shoreline sites in view
        pad = 600
        x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
        fig.update_xaxes(range=[x0, x1])
        fig.update_yaxes(range=[y0, y1])
    fig.update_layout(height=720, width=None, title=None, margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(x=1.01, y=1, font=dict(size=11)))
    return fig


# ---------------------------------------------------------------------------
# Live decisions (Phase B)
# ---------------------------------------------------------------------------
def operator_controls(live: dict, req: dict) -> None:
    shown, rid = req["shown"], req["id"]
    dne = shown["do_not_engage"]
    st.markdown("#### ⏵ Operator decision needed")
    if dne:
        st.markdown(f"The reviewer rejected the analyst's proposal. **Analyst's original proposal:** "
                    f"{shown['analyst_proposal']}")
    c1, c2 = st.columns(2)
    with c1:
        label = "Approve: DO NOT ENGAGE (keep tracking)" if dne else \
                f"Approve: rung {shown['recommended_rung']} as recommended"
        if st.button(label, key=f"accept-{rid}", type="secondary" if dne else "primary", width="stretch"):
            send_answer(live, {"id": rid, "decision": "accept"})
    with c2:
        reason = st.text_input("Reason for rejecting (optional)", key=f"reject-reason-{rid}")
        if st.button("Reject (no action beyond automatic tracking)", key=f"reject-{rid}", width="stretch"):
            send_answer(live, {"id": rid, "decision": "reject", "reason": reason})
    if dne:
        st.markdown("---")
        with st.form(f"override-{rid}"):
            st.markdown("**Override the reviewer.** This requests the analyst's original proposal. It goes "
                        "to the control room marked OPERATOR OVERRODE REVIEWER, with your reason beside "
                        "the reviewer's. It cannot skip rungs: rung 3 and up still need control-room approval.")
            why = st.text_area("Written reason (required)", key=f"override-reason-{rid}")
            if st.form_submit_button("OVERRIDE REVIEWER REJECT — ENGAGE DRONE", type="primary"):
                if not why.strip():
                    st.error("A written reason is required. Nothing was sent.")
                else:
                    send_answer(live, {"id": rid, "decision": "override", "reason": why.strip()})


# ---------------------------------------------------------------------------
# Start a run from the page (Phase B step 4)
# ---------------------------------------------------------------------------
LAUNCH_LOG = RUNS / "launcher.log"          # pipeline output for runs started from this page


def cost_per_step() -> float | None:
    """Average real-run cost per step, from run-index.csv and the archived indexes in runs/archive/
    (for the estimate on the REAL button; archived runs are not shown anywhere else)."""
    cost = steps = 0.0
    for path in [RUNS / "run-index.csv", *sorted((RUNS / "archive").glob("*/run-index.csv"))]:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["dry_run"].strip().lower() == "false" and r["cost_usd"]:
                    cost += float(r["cost_usd"])
                    steps += len(r["steps"].split())
    return cost / steps if steps else None


def start_run(event: str, steps: str, dry: bool, reject: list[int]) -> None:
    """Start pipeline.py --web in the background. The page never calls Claude itself; the pipeline does."""
    cmd = [sys.executable, str(HERE / "pipeline.py"), "--event", event, "--steps", steps, "--web"]
    if dry:
        cmd.append("--dry-run")
        if reject:
            cmd += ["--dry-reject", ",".join(map(str, reject))]
    RUNS.mkdir(parents=True, exist_ok=True)
    log = open(LAUNCH_LOG, "a", encoding="utf-8")
    log.write(f"\n=== {dt.datetime.now().isoformat(timespec='seconds')}  "
              f"{'DRY RUN' if dry else 'REAL RUN (API)'}: event {event}, steps {steps}"
              + (f", reviewer rejects {reject}" if dry and reject else "") + " ===\n")
    log.flush()
    proc = subprocess.Popen(cmd, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log.close()
    st.session_state["launched"] = {"proc": proc, "time": time.time(), "dry": dry}
    st.rerun()


def launch_status() -> None:
    """After Start: 'starting...' until the run shows up, or the error if the pipeline quit early."""
    la = st.session_state.get("launched")
    if not la:
        return
    code = la["proc"].poll()
    if code not in (None, 0):
        tail = LAUNCH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-8:] if LAUNCH_LOG.exists() else []
        st.error(f"The run did not start (exit code {code}). Last lines of runs/launcher.log:\n\n"
                 + "\n".join(f"    {l}" for l in tail))
        if st.button("Dismiss", key="dismiss-launch"):
            st.session_state.pop("launched")
            st.rerun()
    elif code is None and time.time() - la["time"] < 60:
        st.info("Starting the run… the page will switch to it in a few seconds.")
    else:
        st.session_state.pop("launched")


def start_run_panel() -> None:
    with st.expander("Start a run", expanded=False):
        ev = st.selectbox("Event", sorted(events), key="start-event",
                          format_func=lambda e: f"{e}  ·  {truth[e]['Date']} {truth[e]['Start time']}")
        n = len({r["Timestamp"] for r in events[ev]})
        which = st.radio("Steps", ["All", "Last only", "Choose"], horizontal=True, key="start-which")
        chosen = st.multiselect("Which steps", list(range(1, n + 1)), default=[n], key="start-chosen") \
            if which == "Choose" else []
        steps = {"All": "all", "Last only": "last"}.get(which) or ",".join(map(str, sorted(chosen)))
        count = n if which == "All" else 1 if which == "Last only" else len(chosen)
        dry = st.checkbox("Dry run (free: no API calls, canned agent answers)", value=True, key="start-dry")
        reject: list[int] = []
        if dry:
            reject = st.multiselect("Dry-run reviewer REJECTs at steps (to test DO NOT ENGAGE)",
                                    list(range(1, n + 1)), key="start-reject")
        if not steps:
            st.caption("Choose at least one step.")
            return
        if dry:
            if st.button(f"Start DRY RUN: event {ev}, {count} step(s)", key="start-dry-btn", width="stretch"):
                start_run(ev, steps, True, reject)
        else:
            cps = cost_per_step()
            est = f"about ${cps * count:.2f} (${cps:.2f} per step, from your past runs)" if cps else "unknown"
            st.warning(f"**REAL run: calls the Claude API and costs money.** Estimate: {est}.")
            ok = st.checkbox("I confirm: start a REAL run", key="start-confirm")
            if st.button(f"Start REAL run: event {ev}, {count} step(s)", key="start-real-btn", type="primary",
                         disabled=not ok, width="stretch"):
                start_run(ev, steps, False, [])
        st.caption("Decisions are made on this page (--web). No time limits: the run waits for the people.")


ADVICE_COLOR = {"RECOMMEND STOP": "#cf222e", "CONCUR WITH CAUTIONS": "#bf8700", "CONCUR": "#1a7f37"}


def safety_summary(adv: dict | None, hint: bool = True) -> None:
    """The safety agent's call in two bold bullets (control room only). Details stay in the yellow box."""
    if not adv:
        return
    color = ADVICE_COLOR.get(adv.get("advice"), "#57606a")
    st.markdown(f"<div style='font-size:22px;font-weight:700;color:{color}'>"
                f"• Safety agent: {html.escape(str(adv.get('advice', '—')))}</div>", unsafe_allow_html=True)
    if adv.get("safer_alternative"):
        st.markdown(f"<div style='font-size:16px;margin-left:18px'><b>• Safer alternative:</b> "
                    f"{html.escape(adv['safer_alternative'])}</div>", unsafe_allow_html=True)
    if hint:
        st.caption("Safety agent's full concerns and override assessment: the yellow box above.")


def control_room_controls(live: dict, req: dict) -> None:
    rid, rung = req["id"], req.get("requested_rung")
    op = req.get("operator") or {}
    st.markdown("#### ⏵ Control-room decision needed")
    if req.get("overrode_reviewer"):
        st.error("**OPERATOR OVERRODE REVIEWER**")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Reviewer's reasons (REJECT):**  \n{req.get('reviewer_reasons') or '—'}")
        c2.markdown(f"**Operator's reason:**  \n{op.get('reason') or '—'}")
    elif op.get("decision") == "override":
        st.warning(f"**Operator requested a stronger action than recommended.** Reason: {op.get('reason') or '—'}")
    cr_now = D.get_control_room_info(live["event"], req.get("now") or live["now"])["entries"]
    if cr_now:
        st.markdown("**Control-room only information now:**  \n" + "  \n".join(
            f"**{e['control_room_id']}** {e['time'][11:]} — {e['source']}: {e['info']}" for e in cr_now))
    if req.get("advice") is None:
        st.warning("**NO SAFETY ADVICE AVAILABLE.** The request still needs your approval (ROE-4.5).")
    else:
        safety_summary(req["advice"])

    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"Approve: {rung_label(rung)}", key=f"approve-{rid}", type="primary", width="stretch"):
            send_answer(live, {"id": rid, "decision": "approve"})
    with c2:
        with st.form(f"stop-{rid}"):
            why = st.text_area("Reason for stopping (required)", key=f"stop-reason-{rid}")
            if st.form_submit_button("Reject / STOP — do not carry out this request", width="stretch"):
                if not why.strip():
                    st.error("A written reason is required to stop. Nothing was sent.")
                else:
                    send_answer(live, {"id": rid, "decision": "stop", "reason": why.strip()})
    st.caption("Nothing is carried out until you approve (ROE-1.6). You can stop, never step up (ROE-4.4).")


def live_panel(live: dict, view: str) -> None:
    """Buttons (or a waiting note) for the request the pipeline is waiting on, if any."""
    req = live["pending"]
    if not req:
        if live["stale_request"]:
            st.warning("The pipeline stopped answering (its request is more than "
                       f"{PENDING_STALE_S} s old). It was probably closed. No decision can be sent.")
        elif live["humans"] != "web":
            st.caption(f"This run takes its human decisions from {live['humans']} mode, not this page.")
        else:
            st.caption("Agents working… the page updates by itself.")
        return
    if st.session_state.get("sent") == req["id"]:
        st.info("Decision sent. Waiting for the pipeline to pick it up…")
        return
    if req["role"] == "operator":
        if view == "Operator":
            operator_controls(live, req)
        else:
            st.info(f"Waiting for the operator's decision (step {req['step']}).")
    else:                                             # control room request: carries the safety advice
        if view == "Operator":
            st.info(f"Your decision went to the control room (step {req['step']}). Waiting for its decision.")
        else:
            control_room_controls(live, req)


@st.fragment(run_every=1)
def watch_live(sig: tuple | None) -> None:
    """Every second: if a live run started, moved on, or ended, redraw the whole page."""
    if live_signature(find_live()) != sig:
        st.rerun(scope="app")


def decision_chain() -> None:
    """Agents' and people's decisions at this step (saved run or live run), plus live buttons."""
    st.markdown("#### Decision chain" + (" — LIVE" if follow else ""))
    if run_id == "(none)":
        st.caption("No saved run selected. Run the pipeline for this event to see the agents' decisions here.")
    else:
        s = run_step(run_id, now)
        if follow and not (s or {}).get("shown_to_operator"):
            st.caption(f"Step {live['step']}: analyst and reviewer working…")
        elif not s:
            st.caption(f"Run {run_id} did not run a step at {now[11:]}. Move the slider to a step it ran.")
        else:
            a = s.get("analyst", {})
            shown = s.get("shown_to_operator", {}).get("shown", {})
            dne = shown.get("do_not_engage")
            # Quick-decision line: what the operator is being asked to approve
            if dne:
                st.markdown("<div style='font-size:28px;font-weight:700;color:#cf222e'>DO NOT ENGAGE</div>",
                            unsafe_allow_html=True)
            elif "recommended_rung" in shown or "recommended_rung" in a:
                st.markdown(f"<div style='font-size:28px;font-weight:700'>"
                            f"{html.escape(rung_label(shown.get('recommended_rung', a.get('recommended_rung'))))}</div>",
                            unsafe_allow_html=True)
            cols = st.columns(3)
            cols[0].metric("Threat", a.get("threat_level", "—"))
            cols[1].metric("Analyst", f"RUNG {a['recommended_rung']}" if "recommended_rung" in a else "—")
            cols[2].metric("Reviewer", (s.get("reviewer") or {}).get("verdict", "—"))
            # Drone identity: the analyst's call, then what the sensors report (option b)
            for t in a.get("tracks", []):
                yn = lambda v: "yes" if v else "no"           # noqa: E731
                st.markdown(f"**Drone {t.get('track_id', '?')} (analyst):** {t.get('classification', '—')} · "
                            f"track confidence {t.get('confidence', '—')} · PID {yn(t.get('pid'))} · "
                            f"PVID {yn(t.get('pvid'))}")
            tids = [t.get("track_id") for t in a.get("tracks", [])] or [None]
            for tid in tids:
                parts = sensor_identity(events[event_id], now, tid)
                if parts:
                    st.markdown(f"**Sensors report{f' ({tid})' if tid else ''}:** " + " · ".join(parts))
            if dne:
                st.error("**REVIEWER: DO NOT ENGAGE** — " + shown.get("reviewer_reasons", ""))
            st.info("**Analyst's recommendation:** " + a.get("recommended_action", shown.get("recommended_action", "")))
            blocked = [o for o in a.get("options", []) if o["status"] == "BLOCKED"]
            if blocked:
                st.markdown("**Blocked options**")
                for o in blocked:
                    st.markdown(f"- **{EQUIP_NAMES.get(o['option'], o['option'])}:** {o['reasons']}")
            op = s.get("operator_decision")
            if op:
                d = op["decision"]
                st.markdown(f"**Operator** ({d['source']}): **{d['decision'].upper()}**"
                            + (f" — {d['reason']}" if d.get("reason") else "")
                            + f" → requests **{rung_label(op['requested_rung'])}**")
            if view == "Control room":
                if op and op["requested_rung"] >= 3 or (op and op["decision"]["decision"] == "override"):
                    st.markdown(f"<div style='font-size:22px;font-weight:700'>Control room asked to approve: "
                                f"{html.escape(rung_label(op['requested_rung']))}</div>", unsafe_allow_html=True)
                adv = s.get("safety")
                if adv and not (follow and (live.get("pending") or {}).get("role") == "control_room"):
                    safety_summary(adv, hint=False)       # live: shown next to the buttons instead
                if adv:
                    st.warning(f"**Safety agent: {adv['advice']}** — {adv.get('concerns', '')}")
                    if adv.get("override_assessment") and adv["override_assessment"] != "no override":
                        st.markdown(f"*Override assessment:* {adv['override_assessment']}")
                crd = s.get("control_room_decision")
                if crd:
                    d = crd["decision"]
                    st.markdown(f"**Control room** ({d['source']}): **{d['decision'].upper()}**"
                                + (f" — {d['reason']}" if d.get("reason") else ""))
            end = s.get("step_end")
            if end:
                st.success(f"**Outcome:** {end['outcome']}  ·  step cost ${end.get('cost_usd', 0):.4f}")
        if follow:
            live_panel(live, view)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
events = load_events()
truth = {}
with open(ROOT / "inputs" / "events-truth.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        truth[r["Event ID"]] = r

live = find_live()
finished = None
if not live and st.session_state.get("last_live"):
    # The run we were watching just ended: stay on it (same event, that run, its last step)
    # instead of falling back to event 01. Widget values must be set before the widgets exist.
    finished = st.session_state.pop("last_live")
    if finished["followed"]:
        st.session_state["event"] = finished["event"]
        st.session_state["incl-dry"] = st.session_state.get("incl-dry", False) or finished["dry"]
        st.session_state["replay-run"] = finished["run_id"]
        st.session_state["time"] = last_step_time(finished["run_id"]) or finished["now"]

with st.sidebar:
    st.markdown("### Fort GBUS")
    view = st.radio("View", ["Operator", "Control room"], horizontal=True)
    follow = bool(live and live["now"]) and st.toggle("Follow the live run", value=True, key="follow")
    if follow:
        event_id, now = live["event"], live["now"]
        times = sorted({r["Timestamp"] for r in events[event_id]})
        st.markdown(f"**LIVE** run `{live['run_id']}`  \nEvent {event_id} · {now[11:]} · step {live['step']}"
                    + ("  \n*dry run (no API calls)*" if live["dry_run"] else ""))
        run_id = live["run_id"]
        zoom = st.checkbox("Zoom to the action", value=True)
        st.session_state["last_live"] = {"run_id": live["run_id"], "event": event_id, "now": now,
                                         "dry": bool(live["dry_run"]), "followed": True}
    else:
        if live:
            st.caption(f"A live run is in progress: {live['run_id']}")
        if live:
            st.session_state["last_live"] = {"run_id": live["run_id"], "event": live["event"],
                                             "now": live["now"], "dry": bool(live["dry_run"]), "followed": False}
        event_id = st.selectbox("Event", sorted(events), key="event",
                                format_func=lambda e: f"{e}  ·  {truth[e]['Date']} {truth[e]['Start time']}")
        times = sorted({r["Timestamp"] for r in events[event_id]})
        if st.session_state.get("time") not in times:
            st.session_state["time"] = times[-1]          # default: the event's last moment
        now = st.select_slider("Time (replay)", options=times, key="time", format_func=lambda t: t[11:])
        zoom = st.checkbox("Zoom to the action", value=True)
        incl_dry = st.checkbox("Include dry runs", key="incl-dry")
        runs = runs_for(event_id, incl_dry, finished["run_id"] if finished and finished["followed"] else None)
        options = ["(none)"] + runs[::-1]
        if st.session_state.get("replay-run") not in options:
            st.session_state["replay-run"] = "(none)"
        run_id = st.selectbox("Saved run to replay", options, key="replay-run") if runs else "(none)"
    if not live and not st.session_state.get("launched"):
        start_run_panel()
    with st.expander("Escalation ladder (what the rungs mean)", expanded=True):
        st.markdown("| Rung | Action | Min threat | Approval |\n|---|---|---|---|\n" + "\n".join(
            f"| {n} | {m['action']} | {m['min_threat']} | {m['approval']} |" for n, m in load_ladder().items()))
        st.caption("From ROE-4.1. Least force that works; step up only when needed.")
    st.caption("All data is fictional. This page never calls Claude itself; runs (started here or from "
               "the command line) are done by pipeline.py.")

watch_live(live_signature(live))
if not live:
    launch_status()
elif st.session_state.get("launched"):
    st.session_state.pop("launched")              # the run we started is now live
if finished:
    st.success(f"Live run {finished['run_id']} finished."
               + (" It is selected below for replay: use the Time slider to step back through it, and "
                  "switch View to see both sides." if finished["followed"] else " Its log is in the runs folder."))

rows = events[event_id]
weather = D.get_weather(now, full=True)   # viewer: keep source / notional
notices = D.get_notices(now)["notices"]
health = D.get_health_status(now)["equipment"]

# Header
step_no = times.index(now) + 1
st.markdown(f"## FORT GBUS · Counter-Drone {view} — Event {event_id} · "
            f"{now[:10]} {now[11:]} · step {step_no} of {len(times)}")
c1, c2 = st.columns([1, 2])
with c1:
    if weather.get("available"):
        c = weather["conditions"]
        st.markdown(f"**Weather:** {c.get('summary', c)}"
                    + (" · *notional*" if c.get("notional") else "")
                    + (f"  \n<span style='font-size:12px;color:#57606a'>{html.escape(c['adjusted_note'])}</span>"
                       if c.get("adjusted_note") else ""), unsafe_allow_html=True)
    else:
        st.markdown("**Weather:** not available yet (Rochester forecast pending)")
with c2:
    st.markdown("**Notices in effect:** " + (", ".join(f"{n['notice_id']} {n['title']}" for n in notices) or "none"))

if follow:                                  # live: decisions first, above the map
    st.markdown("---")
    decision_chain()
    st.markdown("---")

left, right = st.columns([3, 1])
with left:
    st.plotly_chart(event_map(rows, now, zoom), key="map")
with right:
    st.markdown("#### System status")
    for group, ids in (("Sensors", D.SENSORS), ("Defeat options", D.DEFEAT)):
        st.markdown(f"**{group}**")
        for eq in ids:
            h = health[eq]
            color = STATUS_COLOR[h["status"]]
            note = f" — {h['health_id']}: {html.escape(h['reason'])}" if "health_id" in h else ""
            st.markdown(f"<span style='color:{color};font-size:18px'>●</span> "
                        f"<b>{EQUIP_NAMES[eq]}</b> <span style='color:{color}'>{h['status'].upper()}</span>"
                        f"<span style='font-size:12px;color:#57606a'>{note}</span>",
                        unsafe_allow_html=True)
    if view == "Control room":
        st.markdown("#### Control-room only")
        cr = D.get_control_room_info(event_id, now)["entries"]
        if cr:
            for e in cr:
                st.warning(f"**{e['control_room_id']}** {e['time'][11:]} — {e['source']}: {e['info']}")
        else:
            st.caption("No control-room information yet.")

if not follow:
    st.markdown("---")
    decision_chain()

# Latest readings
with st.expander("Sensor readings at this moment"):
    latest = [{k: v for k, v in r.items() if v} for r in rows if r["Timestamp"] == now]
    st.dataframe(latest, hide_index=True)
