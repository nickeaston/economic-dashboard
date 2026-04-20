#!/usr/bin/env python3
"""
Generate a self-contained economic dashboard HTML file.
Reads economic_data.json and embeds all data inline.

Features:
  - Latest value badge centred above every chart line
  - Period-over-period % change (current vs previous data point)
  - Zoom buttons  : 1M / 3M / 6M / 1Y / 3Y / All  per chart
  - Regenerate button : hits POST /regenerate on the local server

Run:  python3 generate_dashboard.py
"""
import json, os
from datetime import datetime

DATA_FILE   = os.path.join(os.path.dirname(__file__), "economic_data.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "economic_dashboard.html")

with open(DATA_FILE) as f:
    data = json.load(f)

meta    = data.get("_meta", {})
updated = meta.get("updated", "unknown")
source  = meta.get("source", "")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────
SECTIONS = [
    ("au_markets", "Australian Markets", [
        {"id": "asx200",   "title": "ASX S&P 200",      "key": "asx200",   "type": "line", "unit": "pts"},
        {"id": "allords",  "title": "ASX All Ords",      "key": "allords",  "type": "line", "unit": "pts"},
        {"id": "smallcap", "title": "ASX Small Cap",     "key": "smallcap", "type": "line", "unit": "pts"},
        {"id": "audusd",   "title": "AUD/USD",           "key": "audusd",   "type": "line", "unit": ""},
    ]),
    ("au_economy", "Australian Economy", [
        {"id": "unemployment",  "title": "Unemployment Rate",              "key": "unemployment",  "type": "line", "unit": "%"},
        {"id": "interest_rate", "title": "RBA Cash Rate",                  "key": "interest_rate", "type": "line", "unit": "%"},
        {"id": "deficit",       "title": "Budget Deficit/Surplus (% GDP)", "key": "deficit",       "type": "bar",  "unit": "%"},
        {"id": "private_debt",  "title": "Private Debt (% GDP)",           "key": "private_debt",  "type": "line", "unit": "%"},
        {"id": "bonds",         "title": "AU Bond Yields",                 "key": "bonds",         "type": "multiline",
         "fields": [
             {"field": "y2",  "label": "Short-term"},
             {"field": "y10", "label": "10-Year"},
         ], "unit": "%"},
        {"id": "cpi",           "title": "CPI & Inflation",                "key": "cpi",           "type": "dual",
         "fields": [
             {"field": "cpi",       "label": "CPI Index",      "yAxis": "y"},
             {"field": "inflation", "label": "Inflation Rate", "yAxis": "y1"},
         ], "unit": ""},
    ]),
    ("commodities", "Commodities", [
        {"id": "oil",      "title": "WTI Crude Oil",  "key": "oil",      "type": "line", "unit": "USD/bbl"},
        {"id": "gold",     "title": "Gold",           "key": "gold",     "type": "line", "unit": "USD/oz"},
        {"id": "iron_ore", "title": "Iron Ore",       "key": "iron_ore", "type": "line", "unit": "USD/t"},
        {"id": "copper",   "title": "Copper",         "key": "copper",   "type": "line", "unit": "USD/t"},
        {"id": "nickel",   "title": "Nickel",         "key": "nickel",   "type": "line", "unit": "Index 2016=100"},
        {"id": "lithium",  "title": "Lithium",        "key": "lithium",  "type": "line", "unit": "USD/t"},
        {"id": "cobalt",   "title": "Cobalt",         "key": "cobalt",   "type": "line", "unit": "USD/t"},
    ]),
    ("global_markets", "Global Markets", [
        {"id": "dow",      "title": "Dow Jones",              "key": "dow",      "type": "line", "unit": "pts"},
        {"id": "nasdaq",   "title": "NASDAQ",                 "key": "nasdaq",   "type": "line", "unit": "pts"},
        {"id": "sp500",    "title": "S&P 500",                "key": "sp500",    "type": "line", "unit": "pts"},
        {"id": "japan",    "title": "Nikkei 225 (Japan)",     "key": "japan",    "type": "line", "unit": "pts"},
        {"id": "china",    "title": "Shanghai SSE",           "key": "china",    "type": "line", "unit": "pts"},
        {"id": "dax",      "title": "DAX (Germany)",          "key": "dax",      "type": "line", "unit": "pts"},
        {"id": "cac",      "title": "CAC 40 (France)",        "key": "cac",      "type": "line", "unit": "pts"},
        {"id": "ftse",     "title": "FTSE 100 (UK)",          "key": "ftse",     "type": "line", "unit": "pts"},
        {"id": "emerging", "title": "MSCI Emerging Markets",  "key": "emerging", "type": "line", "unit": "pts"},
    ]),
    ("country_debt", "Country Debt-to-GDP", [
        {"id": "country_debt", "title": "Government & Private Debt (% of GDP)",
         "key": "country_debt", "type": "grouped_bar", "unit": "%"},
    ]),
]

COLORS = [
    "#4FC3F7", "#81C784", "#FFB74D", "#F06292", "#CE93D8",
    "#80DEEA", "#FFCC80", "#A5D6A7", "#EF9A9A", "#90CAF9",
]

ZOOM_BUTTONS = [
    ("1M",  1),
    ("3M",  3),
    ("6M",  6),
    ("1Y",  12),
    ("3Y",  36),
    ("All", 0),
]


def fmt_val(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


# ─────────────────────────────────────────────────────────────────────────────
# Latest value stats (computed in Python → injected as static HTML overlay)
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_number(v: float, unit: str = "") -> str:
    if v is None:
        return "—"
    if v >= 100000:
        return f"{v:,.0f}"
    if v >= 1000:
        return f"{v:,.1f}"
    if v >= 100:
        return f"{v:.1f}"
    return f"{v:.2f}"


def latest_stats(cfg: dict) -> dict:
    """Return latest value, date, and % change vs previous data point."""
    key   = cfg["key"]
    ctype = cfg["type"]
    unit  = cfg.get("unit", "")
    d     = data.get(key, {})

    if ctype in ("line", "bar"):
        series = d.get("series", [])
        if not series:
            return {}
        # Find last non-null
        last = prev = None
        for pt in reversed(series):
            v = pt.get("value")
            if v is not None:
                if last is None:
                    last = pt
                elif prev is None:
                    prev = pt
                    break
        if last is None:
            return {}
        lv = last["value"]
        pv = prev["value"] if prev else None
        pct = None
        direction = "flat"
        if pv is not None and pv != 0:
            pct = (lv - pv) / abs(pv) * 100
            direction = "up" if pct > 0.05 else ("down" if pct < -0.05 else "flat")
        return {
            "val":       _fmt_number(lv, unit),
            "unit":      unit,
            "date":      last.get("date", ""),
            "pct":       pct,
            "direction": direction,
            "prev_date": prev.get("date", "") if prev else "",
        }

    elif ctype == "multiline":
        series = d.get("series", [])
        fields = cfg.get("fields", [])
        if not series or not fields:
            return {}
        # Build per-field last values
        parts = []
        lasts = {}
        prevs = {}
        for f in fields:
            fname = f["field"]
            found_last = False
            for pt in reversed(series):
                v = pt.get(fname)
                if v is None:
                    continue
                if not found_last:
                    lasts[fname] = pt
                    found_last = True
                else:
                    prevs[fname] = pt
                    break
            if fname in lasts:
                parts.append(f"{f['label']}: {_fmt_number(lasts[fname].get(fname))}")
        # Primary field for pct change
        pf    = fields[0]["field"]
        lv    = lasts[pf].get(pf) if pf in lasts else None
        ppt   = prevs.get(pf)
        pv    = ppt.get(pf) if ppt else None
        pct   = None
        direction = "flat"
        if lv is not None and pv is not None and pv != 0:
            pct = (lv - pv) / abs(pv) * 100
            direction = "up" if pct > 0.05 else ("down" if pct < -0.05 else "flat")
        date = lasts[pf].get("date", "") if pf in lasts else ""
        return {
            "val":       " · ".join(parts),
            "unit":      unit,
            "date":      date,
            "pct":       pct,
            "direction": direction,
            "prev_date": ppt.get("date", "") if ppt else "",
            "multi":     True,
        }

    elif ctype == "dual":
        series = d.get("series", [])
        fields = cfg.get("fields", [])
        if not series or not fields:
            return {}
        parts = []
        for f in fields:
            fname = f["field"]
            for pt in reversed(series):
                v = pt.get(fname)
                if v is not None:
                    parts.append(f"{f['label']}: {_fmt_number(v)}")
                    break
        return {"val": " · ".join(parts), "unit": "", "date": "", "pct": None,
                "direction": "flat", "multi": True}

    return {}


def render_overlay(cfg: dict) -> str:
    stats = latest_stats(cfg)
    if not stats:
        return ""
    val   = stats.get("val", "—")
    unit  = stats.get("unit", "")
    pct   = stats.get("pct")
    dirn  = stats.get("direction", "flat")
    multi = stats.get("multi", False)

    # Change badge
    change_html = ""
    if pct is not None:
        arrow = "▲" if dirn == "up" else ("▼" if dirn == "down" else "—")
        sign  = "+" if pct > 0 else ""
        change_html = (f'<span class="lo-change {dirn}">'
                       f'{arrow} {sign}{pct:.1f}%</span>')

    if multi:
        val_html = f'<span class="lo-val lo-small">{val}</span>'
    else:
        unit_html = f' <span class="lo-unit">{unit}</span>' if unit else ""
        val_html  = f'<span class="lo-val">{val}</span>{unit_html}'

    return (f'<div class="latest-overlay">'
            f'{val_html}{change_html}'
            f'</div>')


# ─────────────────────────────────────────────────────────────────────────────
# Zoom buttons HTML
# ─────────────────────────────────────────────────────────────────────────────

def render_zoom_btns(cid: str) -> str:
    btns = []
    for label, months in ZOOM_BUTTONS:
        active = ' active' if months == 0 else ''
        btns.append(
            f'<button class="zoom-btn{active}" '
            f'data-months="{months}" '
            f'onclick="applyZoom(\'{cid}\',{months},this)">'
            f'{label}</button>'
        )
    return (f'<div class="zoom-bar" id="zoom-{cid}">'
            + "".join(btns)
            + '</div>')


# ─────────────────────────────────────────────────────────────────────────────
# Chart JS builders
# ─────────────────────────────────────────────────────────────────────────────

def _chart_options(unit: str, cid: str) -> str:
    """Common options block with unit and latest-value plugin config."""
    return f"""{{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ labels: {{ color: '#cdd6f4' }} }},
          latestValueLabel: {{ unit: {json.dumps(unit)} }},
          tooltip: {{ callbacks: {{ label: function(c) {{
            return c.dataset.label + ': ' + c.parsed.y.toLocaleString() + ' {unit}';
          }} }} }}
        }},
        scales: {{
          x: {{ ticks: {{ color: '#a6adc8', maxTicksLimit: 10 }}, grid: {{ color: '#313244' }} }},
          y: {{ ticks: {{ color: '#a6adc8' }}, grid: {{ color: '#313244' }},
                title: {{ display: {json.dumps(bool(unit))}, text: {json.dumps(unit)}, color: '#a6adc8' }} }}
        }}
      }}"""


def build_chart_js(cfg: dict) -> str:
    cid   = cfg["id"]
    key   = cfg["key"]
    ctype = cfg["type"]
    unit  = cfg.get("unit", "")
    d     = data.get(key, {})

    if ctype == "line":
        series  = d.get("series", [])
        labels  = [p["date"] for p in series]
        values  = [p.get("value") for p in series]
        label   = d.get("label", cfg["title"])
        return f"""
  (function() {{
    var ctx = document.getElementById('chart-{cid}').getContext('2d');
    var ch = new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: {json.dumps(labels)},
        datasets: [{{
          label: {json.dumps(label)},
          data: {json.dumps(values)},
          borderColor: '#4FC3F7',
          backgroundColor: 'rgba(79,195,247,0.07)',
          borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
        }}]
      }},
      options: {_chart_options(unit, cid)}
    }});
    storeOrig('{cid}', ch);
  }})();"""

    elif ctype == "bar":
        series = d.get("series", [])
        labels = [p["date"] for p in series]
        values = [p.get("value") for p in series]
        label  = d.get("label", cfg["title"])
        colors = [
            "rgba(129,199,132,0.8)" if (v is not None and v >= 0) else "rgba(239,154,154,0.8)"
            for v in values
        ]
        return f"""
  (function() {{
    var ctx = document.getElementById('chart-{cid}').getContext('2d');
    var ch = new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: {json.dumps(labels)},
        datasets: [{{
          label: {json.dumps(label)},
          data: {json.dumps(values)},
          backgroundColor: {json.dumps(colors)},
          borderWidth: 0,
        }}]
      }},
      options: {_chart_options(unit, cid)}
    }});
    storeOrig('{cid}', ch);
  }})();"""

    elif ctype == "multiline":
        series  = d.get("series", [])
        fields  = cfg["fields"]
        labels  = [p["date"] for p in series]
        datasets = []
        for i, f in enumerate(fields):
            vals = [p.get(f["field"]) for p in series]
            datasets.append({
                "label": f["label"], "data": vals,
                "borderColor": COLORS[i % len(COLORS)],
                "backgroundColor": "transparent",
                "borderWidth": 2, "pointRadius": 0, "tension": 0.3,
            })
        return f"""
  (function() {{
    var ctx = document.getElementById('chart-{cid}').getContext('2d');
    var ch = new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: {json.dumps(labels)},
        datasets: {json.dumps(datasets)}
      }},
      options: {_chart_options(unit, cid)}
    }});
    storeOrig('{cid}', ch);
  }})();"""

    elif ctype == "dual":
        series   = d.get("series", [])
        fields   = cfg["fields"]
        labels   = [p["date"] for p in series]
        datasets = []
        for i, f in enumerate(fields):
            vals = [p.get(f["field"]) for p in series]
            ds   = {
                "label": f["label"], "data": vals,
                "borderColor": COLORS[i % len(COLORS)],
                "backgroundColor": "transparent",
                "borderWidth": 2, "pointRadius": 0, "tension": 0.3,
                "yAxisID": f["yAxis"],
            }
            datasets.append(ds)
        return f"""
  (function() {{
    var ctx = document.getElementById('chart-{cid}').getContext('2d');
    var ch = new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: {json.dumps(labels)},
        datasets: {json.dumps(datasets)}
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ labels: {{ color: '#cdd6f4' }} }},
          latestValueLabel: {{ unit: '' }},
        }},
        scales: {{
          x:  {{ ticks: {{ color: '#a6adc8', maxTicksLimit: 10 }}, grid: {{ color: '#313244' }} }},
          y:  {{ type: 'linear', position: 'left',  ticks: {{ color: '#4FC3F7' }},
                 grid: {{ color: '#313244' }},
                 title: {{ display: true, text: 'CPI Index',    color: '#4FC3F7' }} }},
          y1: {{ type: 'linear', position: 'right', ticks: {{ color: '#81C784' }},
                 grid: {{ drawOnChartArea: false }},
                 title: {{ display: true, text: 'Inflation %', color: '#81C784' }} }}
        }}
      }}
    }});
    storeOrig('{cid}', ch);
  }})();"""

    elif ctype == "grouped_bar":
        govt    = d.get("govt", {})
        private = d.get("private", {})
        countries  = sorted(set(list(govt.keys()) + list(private.keys())))
        govt_vals  = [govt.get(c) for c in countries]
        priv_vals  = [private.get(c) for c in countries]
        return f"""
  (function() {{
    var ctx = document.getElementById('chart-{cid}').getContext('2d');
    var ch = new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: {json.dumps(countries)},
        datasets: [
          {{ label: 'Government Debt',
             data: {json.dumps(govt_vals)},
             backgroundColor: 'rgba(79,195,247,0.75)', borderWidth: 0 }},
          {{ label: 'Private Debt',
             data: {json.dumps(priv_vals)},
             backgroundColor: 'rgba(240,98,146,0.75)', borderWidth: 0 }}
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ labels: {{ color: '#cdd6f4' }} }},
          latestValueLabel: {{ unit: '' }},
          tooltip: {{ callbacks: {{ label: function(c) {{
            return c.dataset.label + ': ' + (c.parsed.y !== null ? c.parsed.y + ' {unit}' : '—');
          }} }} }}
        }},
        scales: {{
          x: {{ ticks: {{ color: '#a6adc8' }}, grid: {{ color: '#313244' }} }},
          y: {{ ticks: {{ color: '#a6adc8' }}, grid: {{ color: '#313244' }},
                title: {{ display: true, text: '% of GDP', color: '#a6adc8' }} }}
        }}
      }}
    }});
    storeOrig('{cid}', ch);
  }})();"""

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Table HTML
# ─────────────────────────────────────────────────────────────────────────────

def build_table_html(cfg: dict) -> str:
    cid   = cfg["id"]
    key   = cfg["key"]
    ctype = cfg["type"]
    d     = data.get(key, {})

    if ctype in ("line", "bar"):
        series = d.get("series", [])
        rows = "".join(
            f"<tr><td>{p['date']}</td>"
            f"<td class='num'>{fmt_val(p.get('value'))}</td></tr>"
            for p in reversed(series)
        )
        return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>Date</th><th>Value</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

    elif ctype == "multiline":
        series = d.get("series", [])
        fields = cfg["fields"]
        headers = "".join(f"<th>{f['label']}</th>" for f in fields)
        rows = "".join(
            "<tr><td>{}</td>{}</tr>".format(
                p["date"],
                "".join(
                    f"<td class='num'>{fmt_val(p.get(f['field']))}</td>"
                    for f in fields
                )
            )
            for p in reversed(series)
        )
        return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>Date</th>{headers}</tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

    elif ctype == "dual":
        series = d.get("series", [])
        fields = cfg["fields"]
        headers = "".join(f"<th>{f['label']}</th>" for f in fields)
        rows = "".join(
            "<tr><td>{}</td>{}</tr>".format(
                p["date"],
                "".join(
                    f"<td class='num'>{fmt_val(p.get(f['field']))}</td>"
                    for f in fields
                )
            )
            for p in reversed(series)
        )
        return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>Date</th>{headers}</tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

    elif ctype == "grouped_bar":
        govt    = d.get("govt", {})
        private = d.get("private", {})
        countries = sorted(set(list(govt.keys()) + list(private.keys())))
        rows = "".join(
            f"<tr><td>{c}</td>"
            f"<td class='num'>{fmt_val(govt.get(c))}</td>"
            f"<td class='num'>{fmt_val(private.get(c))}</td></tr>"
            for c in countries
        )
        return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>Country</th><th>Govt Debt (%)</th><th>Private Debt (%)</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar nav
# ─────────────────────────────────────────────────────────────────────────────

def build_nav() -> str:
    items = []
    for sec_id, sec_title, charts in SECTIONS:
        items.append(
            f'<li class="nav-section"><a href="#{sec_id}">{sec_title}</a><ul>'
        )
        for cfg in charts:
            items.append(
                f'  <li><a href="#metric-{cfg["id"]}">{cfg["title"]}</a></li>'
            )
        items.append('</ul></li>')
    return "\n".join(items)


# ─────────────────────────────────────────────────────────────────────────────
# Main content
# ─────────────────────────────────────────────────────────────────────────────

def build_content():
    sections_html = []
    all_js        = []

    for sec_id, sec_title, charts in SECTIONS:
        metrics_html = []
        for cfg in charts:
            cid        = cfg["id"]
            table_html = build_table_html(cfg)
            chart_js   = build_chart_js(cfg)
            overlay    = render_overlay(cfg)
            zoom_html  = render_zoom_btns(cid)
            all_js.append(chart_js)

            metrics_html.append(f"""
      <div class="metric" id="metric-{cid}">
        <h3>{cfg['title']}</h3>
        {zoom_html}
        <div class="metric-body">
          <div class="chart-container">
            {overlay}
            <canvas id="chart-{cid}"></canvas>
          </div>
          {table_html}
        </div>
      </div>""")

        sections_html.append(f"""
    <section id="{sec_id}">
      <h2 class="section-title">{sec_title}</h2>
      {"".join(metrics_html)}
    </section>""")

    return "".join(sections_html), "\n".join(all_js)


# ─────────────────────────────────────────────────────────────────────────────
# Assemble HTML
# ─────────────────────────────────────────────────────────────────────────────

nav_html, (content_html, charts_js) = build_nav(), build_content()

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Economic Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:       #1e1e2e;
    --surface:  #24273a;
    --surface2: #2a2d3e;
    --border:   #313244;
    --text:     #cdd6f4;
    --muted:    #a6adc8;
    --accent:   #4FC3F7;
    --accent2:  #81C784;
    --sidebar-w: 240px;
  }}

  html {{ scroll-behavior: smooth; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    display: flex;
    min-height: 100vh;
  }}

  /* ── Sidebar ── */
  #sidebar {{
    width: var(--sidebar-w);
    background: var(--surface);
    border-right: 1px solid var(--border);
    position: fixed;
    top: 0; left: 0; bottom: 0;
    overflow-y: auto;
    padding: 20px 0;
    z-index: 100;
  }}
  #sidebar .logo {{
    padding: 0 18px 16px;
    font-size: 15px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: 0.02em;
    border-bottom: 1px solid var(--border);
    margin-bottom: 10px;
  }}
  #sidebar .logo small {{
    display: block;
    font-size: 11px;
    font-weight: 400;
    color: var(--muted);
    margin-top: 2px;
  }}
  #sidebar ul {{ list-style: none; }}
  #sidebar li.nav-section > a {{
    display: block;
    padding: 8px 18px 4px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    text-decoration: none;
    margin-top: 6px;
  }}
  #sidebar li.nav-section > a:hover {{ color: var(--accent); }}
  #sidebar li.nav-section ul li a {{
    display: block;
    padding: 4px 18px 4px 28px;
    color: var(--muted);
    text-decoration: none;
    font-size: 13px;
    transition: color 0.15s, background 0.15s;
    border-radius: 4px;
    margin: 1px 6px;
  }}
  #sidebar li.nav-section ul li a:hover {{ color: var(--text); background: var(--surface2); }}

  /* ── Main ── */
  #main {{
    margin-left: var(--sidebar-w);
    flex: 1;
    padding: 30px 32px 60px;
    max-width: 1400px;
  }}
  h1.dashboard-title {{
    font-size: 22px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
  }}
  .header-row {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 32px;
  }}
  .updated-tag {{
    font-size: 12px;
    color: var(--muted);
    flex: 1;
  }}
  .updated-tag small {{
    display: block;
    font-size: 10px;
    color: #6b7280;
    margin-top: 2px;
  }}
  #regen-btn {{
    background: #2d6a3f;
    color: #a6f4c5;
    border: 1px solid #3d8a52;
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s;
  }}
  #regen-btn:hover {{ background: #378a50; }}
  #regen-btn.loading {{ opacity: 0.6; cursor: wait; }}
  #regen-msg {{
    font-size: 11px;
    color: var(--muted);
    min-width: 120px;
  }}

  /* ── Sections ── */
  section {{ margin-bottom: 48px; }}
  h2.section-title {{
    font-size: 16px;
    font-weight: 700;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 20px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}

  /* ── Metric card ── */
  .metric {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .metric h3 {{
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 10px;
  }}

  /* ── Zoom buttons ── */
  .zoom-bar {{
    display: flex;
    gap: 4px;
    margin-bottom: 12px;
  }}
  .zoom-btn {{
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 3px 9px;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .zoom-btn:hover {{ color: var(--text); border-color: var(--accent); }}
  .zoom-btn.active {{
    background: var(--accent);
    color: var(--bg);
    border-color: var(--accent);
    font-weight: 600;
  }}

  /* ── Chart container ── */
  .metric-body {{
    display: grid;
    grid-template-columns: 1fr 320px;
    gap: 20px;
    align-items: start;
  }}
  @media (max-width: 900px) {{ .metric-body {{ grid-template-columns: 1fr; }} }}

  .chart-container {{
    position: relative;
    height: 260px;
    width: 100%;
  }}

  /* ── Latest value overlay (inside chart-container, centred top) ── */
  .latest-overlay {{
    position: absolute;
    top: 8px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10;
    display: flex;
    align-items: baseline;
    gap: 6px;
    background: rgba(30, 30, 46, 0.88);
    padding: 3px 12px 4px;
    border-radius: 5px;
    pointer-events: none;
    white-space: nowrap;
    border: 1px solid rgba(79,195,247,0.18);
  }}
  .lo-val {{
    font-size: 16px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.02em;
  }}
  .lo-val.lo-small {{
    font-size: 12px;
    letter-spacing: 0;
  }}
  .lo-unit {{
    font-size: 11px;
    color: var(--muted);
    margin-left: 1px;
  }}
  .lo-change {{
    font-size: 11px;
    font-weight: 600;
    padding: 1px 5px;
    border-radius: 3px;
    margin-left: 2px;
  }}
  .lo-change.up   {{ color: #81C784; background: rgba(129,199,132,0.12); }}
  .lo-change.down {{ color: #EF9A9A; background: rgba(239,154,154,0.12); }}
  .lo-change.flat {{ color: var(--muted); }}

  /* ── Table ── */
  .table-wrap {{
    max-height: 280px;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: 6px;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }}
  thead {{
    position: sticky;
    top: 0;
    background: var(--surface2);
    z-index: 1;
  }}
  th {{
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  td {{
    padding: 6px 10px;
    color: var(--text);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  td.num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover {{ background: var(--surface2); }}

  /* ── Scrollbar ── */
  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
</head>
<body>

<nav id="sidebar">
  <div class="logo">
    Economic Dashboard
    <small>Updated: {updated}</small>
  </div>
  <ul>
    {nav_html}
  </ul>
</nav>

<main id="main">
  <h1 class="dashboard-title">Economic Dashboard</h1>
  <div class="header-row">
    <div class="updated-tag">
      Data last updated: {updated}
      <small>{source}</small>
    </div>
    <span id="regen-msg"></span>
    <a id="regen-btn" href="https://github.com/nickeaston/economic-dashboard/actions/workflows/refresh.yml" target="_blank" rel="noopener" style="text-decoration:none;">&#8635; Refresh Now</a>
  </div>

  {content_html}
</main>

<script>
// ── Latest-value annotation plugin ───────────────────────────────────────────
Chart.register({{
  id: 'latestValueLabel',
  afterDraw: function(chart) {{
    var opts = chart.config.options.plugins && chart.config.options.plugins.latestValueLabel;
    if (!opts) return;
    var datasets = chart.data.datasets;
    if (!datasets || !datasets.length) return;

    var ca  = chart.chartArea;
    var ctx = chart.ctx;

    // Find the last non-null value across all primary datasets (first one)
    var ds = datasets[0];
    var lastIdx = ds.data.length - 1;
    while (lastIdx >= 0 && (ds.data[lastIdx] == null)) lastIdx--;
    if (lastIdx < 0) return;

    var val = ds.data[lastIdx];
    if (typeof val !== 'number') return;

    // Draw a small dot indicator at the last data point
    var meta = chart.getDatasetMeta(0);
    var pt   = meta.data[lastIdx];
    if (!pt) return;

    ctx.save();
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#4FC3F7';
    ctx.fill();
    ctx.strokeStyle = 'rgba(30,30,46,0.9)';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();
  }}
}});

// ── Original data store for zoom ─────────────────────────────────────────────
var chartOrigData = {{}};

function storeOrig(id, chart) {{
  chartOrigData[id] = {{
    labels:   chart.data.labels.slice(),
    datasets: chart.data.datasets.map(function(ds) {{
      return {{ data: ds.data.slice() }};
    }})
  }};
}}

// ── Zoom function ─────────────────────────────────────────────────────────────
function applyZoom(chartId, months, btn) {{
  var chart = Chart.getChart('chart-' + chartId);
  if (!chart) return;
  var orig = chartOrigData[chartId];
  if (!orig) return;

  var labels = orig.labels;

  if (months === 0) {{
    // Show all
    chart.data.labels = labels.slice();
    chart.data.datasets.forEach(function(ds, i) {{
      ds.data = orig.datasets[i].data.slice();
    }});
  }} else {{
    var cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - months);

    var keep = [];
    labels.forEach(function(lbl, i) {{
      var dt = parseLabel(lbl);
      if (dt && dt >= cutoff) keep.push(i);
    }});

    chart.data.labels = keep.map(function(i) {{ return labels[i]; }});
    chart.data.datasets.forEach(function(ds, i) {{
      ds.data = keep.map(function(j) {{ return orig.datasets[i].data[j]; }});
    }});
  }}

  chart.update();

  // Highlight active button
  if (btn) {{
    var bar = btn.closest('.zoom-bar');
    if (bar) {{
      bar.querySelectorAll('.zoom-btn').forEach(function(b) {{
        b.classList.remove('active');
      }});
      btn.classList.add('active');
    }}
  }}
}}

function parseLabel(lbl) {{
  // Parses d/m/yy or similar
  var parts = lbl.split('/');
  if (parts.length === 3) {{
    var d = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10) - 1;
    var y = parseInt(parts[2], 10);
    if (y < 100) y += 2000;
    return new Date(y, m, d);
  }}
  return null;
}}

// ── Regenerate dashboard ──────────────────────────────────────────────────────
function regenerate() {{
  var btn = document.getElementById('regen-btn');
  var msg = document.getElementById('regen-msg');
  btn.classList.add('loading');
  btn.textContent = '⏳ Updating...';
  msg.textContent = '';
  fetch('/regenerate', {{ method: 'POST' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.ok) {{
        msg.textContent = 'Done — reloading...';
        setTimeout(function() {{ location.reload(); }}, 800);
      }} else {{
        btn.classList.remove('loading');
        btn.textContent = '↻ Regenerate';
        msg.textContent = 'Error: ' + (d.error || 'unknown');
      }}
    }})
    .catch(function(e) {{
      btn.classList.remove('loading');
      btn.textContent = '↻ Regenerate';
      msg.textContent = 'Server not running — start with ./open_dashboard.sh';
    }});
}}

// ── Render charts ─────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', function() {{
{charts_js}
}});
</script>
</body>
</html>
"""

with open(OUTPUT_FILE, "w") as f:
    f.write(HTML)

print(f"Dashboard written to: {OUTPUT_FILE}")
print(f"Sections: {len(SECTIONS)} | Charts: {sum(len(c) for _, _, c in SECTIONS)}")

# Email sending removed 2026-04-20 — dashboard is URL-accessed only.
# Live site: https://nickeaston.github.io/economic-dashboard/
