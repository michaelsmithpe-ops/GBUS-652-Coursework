"""Draw the Fort GBUS site map from inputs/site.json with Plotly.

build_site_figure() is meant to be reused by the Streamlit app later (tracks get added
on top). Running this file writes maps/fort-gbus-map.html (interactive).
No API calls.
"""

import json
import math
from pathlib import Path

import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
SITE_FILE = ROOT / "inputs" / "site.json"
OUT_DIR = ROOT / "maps"

BACKSTOP_COLORS = {          # fill, line
    "Preferred":   ("rgba(46,160,67,0.10)",  "rgba(46,160,67,0.6)"),
    "Conditional": ("rgba(210,153,34,0.25)", "rgba(210,153,34,0.9)"),
    "Never":       ("rgba(207,34,46,0.25)",  "rgba(207,34,46,0.9)"),
}
LAKE_COLOR = "rgba(120,170,220,0.35)"
LAND_COLOR = "rgba(222,210,180,0.45)"


def load_site(path=SITE_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rect_path(z):
    return [(z["x0"], z["y0"]), (z["x1"], z["y0"]), (z["x1"], z["y1"]), (z["x0"], z["y1"]), (z["x0"], z["y0"])]


def _hover(z):
    text = f"<b>{z['id']}</b> {z['name']}<br>Ground hazard: {z['ground_hazard']}<br>Backstop: {z['backstop']}"
    if z.get("condition"):
        text += f" ({z['condition']})"
    return text


def _sector_points(x, y, b_from, b_to, r, n=40):
    span = (b_to - b_from) % 360
    pts = [(x, y)]
    for i in range(n + 1):
        b = math.radians(b_from + span * i / n)
        pts.append((x + r * math.sin(b), y + r * math.cos(b)))
    pts.append((x, y))
    return pts


def build_site_figure(site, show_sectors=True, y_view=(-3300, 7000)):
    ext = site["extent"]
    fig = go.Figure()

    # Background: lake (north of shoreline) and land (south).
    fig.add_shape(type="rect", x0=ext["x_min"], x1=ext["x_max"], y0=site["shoreline_y"], y1=ext["y_max"],
                  fillcolor=LAKE_COLOR, line_width=0, layer="below")
    fig.add_shape(type="rect", x0=ext["x_min"], x1=ext["x_max"], y0=ext["y_min"], y1=site["shoreline_y"],
                  fillcolor=LAND_COLOR, line_width=0, layer="below")

    # Zones (filled polygons, hover shows ratings).
    for z in site["zones"]:
        pts = _rect_path(z) if z["shape"] == "rect" else [tuple(p) for p in z["points"]] + [tuple(z["points"][0])]
        fill, line = BACKSTOP_COLORS[z["backstop"]]
        if z["id"] == "Z-LAKE":
            fill = "rgba(46,160,67,0.06)"
        xs, ys = zip(*pts)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", fill="toself", fillcolor=fill,
            line=dict(color=line, width=1, dash="dot" if z["id"] == "Z-APPR" else "solid"),
            name=z["id"], hoverinfo="text", hovertext=_hover(z), showlegend=False))
        cx, cy = sum(xs[:-1]) / (len(xs) - 1), sum(ys[:-1]) / (len(ys) - 1)
        if z["id"] == "Z-CAN":
            cy = 7000
        if z["id"] == "Z-SHIP":
            cy = 5500
        if z["id"] == "Z-LAKE":
            cy = 3700
        fig.add_annotation(x=cx, y=cy, text=z["name"], showarrow=False,
                           font=dict(size=10, color="#333"))

    # Base boundary.
    b = site["base_boundary"]
    fig.add_shape(type="rect", x0=b["x0"], x1=b["x1"], y0=b["y0"], y1=b["y1"],
                  line=dict(color="#555", width=2, dash="dash"), fillcolor="rgba(0,0,0,0)")
    fig.add_annotation(x=b["x0"] + 50, y=b["y0"] + 120, text="Fort GBUS boundary", showarrow=False,
                       xanchor="left", font=dict(size=10, color="#555"))

    # Lines: border and road.
    for ln in site["lines"]:
        xs, ys = zip(*ln["points"])
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=ln["name"],
                                 line=dict(color="#222" if ln["id"] == "L-BORDER" else "#777",
                                           width=3, dash="dashdot" if ln["id"] == "L-BORDER" else "solid"),
                                 hoverinfo="name", showlegend=False))
    border_y = next(ln for ln in site["lines"] if ln["id"] == "L-BORDER")["points"][0][1]
    fig.add_annotation(x=0, y=border_y, text=f"U.S. / CANADA BORDER (y = {border_y:,})", showarrow=False,
                       yshift=10, font=dict(size=11, color="#222"))
    fig.add_annotation(x=-1500, y=1900, text="<b>LAKE AMERICA</b>", showarrow=False,
                       font=dict(size=26, color="rgba(30,80,140,0.75)", family="Georgia, serif"))
    fig.add_annotation(x=-500, y=-3000, text="Public road", showarrow=False, yshift=-10,
                       font=dict(size=10, color="#555"))

    # Shoreline.
    fig.add_trace(go.Scatter(x=[ext["x_min"], ext["x_max"]], y=[0, 0], mode="lines",
                             line=dict(color="#2a5d8f", width=2), name="Shoreline",
                             hoverinfo="name", showlegend=False))
    fig.add_annotation(x=-3400, y=0, text="Shoreline", showarrow=False, xanchor="left", yshift=-10,
                       font=dict(size=10, color="#2a5d8f"))

    # Gun firing sector.
    if show_sectors:
        defeat = {d["id"]: d for d in site["defeat_options"]}
        for s in site.get("fire_sectors", []):
            d = defeat[s["from"]]
            xs, ys = zip(*_sector_points(d["x"], d["y"], s["bearing_from"], s["bearing_to"], s["range_m"]))
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", fill="toself",
                                     fillcolor="rgba(240,90,90,0.35)",
                                     line=dict(color="rgba(180,20,20,0.9)", width=2, dash="dash"),
                                     name="Gun danger zone", hoverinfo="text",
                                     hovertext=f"<b>Gun danger zone (firing sector)</b><br>{s['bearing_from']:03d}-{s['bearing_to']:03d} deg, "
                                               f"{s['range_m']:,} m<br>{s['rule']}"))
            fig.add_annotation(x=d["x"], y=d["y"] + s["range_m"] * 0.8, text="GUN DANGER ZONE",
                               showarrow=False, font=dict(size=11, color="rgb(150,15,15)"))

    # Acoustic array footprint + nodes.
    a = site["acoustic_array"]
    f = a["footprint"]
    fig.add_shape(type="rect", x0=f["x0"], x1=f["x1"], y0=f["y0"], y1=f["y1"],
                  line=dict(color="rgba(31,111,235,0.7)", width=1, dash="dot"))
    nx, ny = zip(*a["nodes"])
    fig.add_trace(go.Scatter(x=nx, y=ny, mode="markers", name="Acoustic nodes (S-ACO)",
                             marker=dict(symbol="circle", size=6, color="rgba(31,111,235,0.7)"),
                             hoverinfo="text", hovertext=[a["name"]] * len(nx)))

    # Sensors.
    s = site["sensors"]
    fig.add_trace(go.Scatter(
        x=[p["x"] for p in s], y=[p["y"] for p in s], mode="markers+text", name="Sensors",
        marker=dict(symbol="triangle-up", size=13, color="#1f6feb", line=dict(color="white", width=1)),
        text=[p["id"] for p in s], textposition="top center", textfont=dict(size=10, color="#1f6feb"),
        hoverinfo="text", hovertext=[f"<b>{p['id']}</b> {p['name']}<br>({p['x']}, {p['y']}), {p['height']} m" for p in s]))

    # Defeat options.
    d = site["defeat_options"]
    fig.add_trace(go.Scatter(
        x=[p["x"] for p in d], y=[p["y"] for p in d], mode="markers+text", name="Defeat options",
        marker=dict(symbol="diamond", size=13, color="#cf222e", line=dict(color="white", width=1)),
        text=[p["id"] for p in d], textposition="bottom center", textfont=dict(size=10, color="#cf222e"),
        hoverinfo="text", hovertext=[f"<b>{p['id']}</b> {p['name']}<br>({p['x']}, {p['y']})"
                                     + (f"<br>{p['rule']}" if p.get("rule") else "") for p in d]))

    # Origin.
    fig.add_trace(go.Scatter(x=[0], y=[0], mode="markers", name="GRP-0 (origin)",
                             marker=dict(symbol="x", size=9, color="black"), hoverinfo="name"))

    # Legend entries for backstop colors.
    for label, (fill, line) in BACKSTOP_COLORS.items():
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=f"Backstop: {label}",
                                 marker=dict(symbol="square", size=12, color=fill, line=dict(color=line, width=1))))

    fig.update_layout(
        title="Fort GBUS — Site Map (fictional)  ·  grid in meters, north up",
        xaxis=dict(title="x (m east)", range=[ext["x_min"], ext["x_max"]], zeroline=False, showgrid=True,
                   gridcolor="rgba(0,0,0,0.06)"),
        yaxis=dict(title="y (m north)", range=list(y_view), scaleanchor="x", scaleratio=1, zeroline=False,
                   showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
        plot_bgcolor="white", height=850, width=950,
        legend=dict(x=1.01, y=1, bgcolor="rgba(255,255,255,0.8)"),
        margin=dict(l=60, r=20, t=60, b=50),
    )
    return fig


def main():
    OUT_DIR.mkdir(exist_ok=True)
    fig = build_site_figure(load_site())
    out = OUT_DIR / "fort-gbus-map.html"
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"wrote {out.relative_to(ROOT)}  ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
