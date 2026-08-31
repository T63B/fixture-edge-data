#!/usr/bin/env python3
"""
Fixture Edge — deterministic dashboard builder.

Usage:  python3 generate.py today.json log.json ratings.json out.html new_log.json

The daily agent's only job is to research fixtures and odds and write today.json.
Everything after that -- de-vigging, model probabilities, blending, edge
detection, track-record maths and HTML rendering -- happens here, in code, so the
output is consistent from one day to the next.

today.json schema:
{
  "date": "2026-08-31",
  "fixtures": [
    {"league": "Premier League", "home": "Liverpool", "away": "Nottingham Forest",
     "kickoff": "12:30",
     "odds": {"H": 1.44, "D": 5.0, "A": 6.5},      # decimal, best available
     "adjust": {"H": 2.0, "D": -1.0, "A": -1.0},   # optional, percentage points
     "factors": ["injury note", "form note"],       # optional
     "postponed": false}
  ],
  "notes": "optional caveat shown in the footer"
}
"""

import json
import math
import sys
import html as _html
from datetime import datetime, timezone

import model as fe_model
import teams as fe_teams

# Weight given to the model when blending with the market.
#
# SET TO ZERO ON EVIDENCE, NOT PREFERENCE. A walk-forward backtest over 5,103
# out-of-sample matches (see BACKTEST.md) swept this weight from 0 to 1. Brier
# score was minimised at exactly w=0 and rose monotonically with every increase:
#     w=0.00 -> 0.61262   w=0.10 -> 0.61290   w=0.25 -> 0.61373
#     w=0.50 -> 0.61626   w=1.00 -> 0.62554
# The de-vigged market price is the better forecast; blending the model in only
# degrades it. Do not raise this without re-running the sweep and beating 0.61262.
#
# The model is therefore NOT used to move the forecast. It is retained for two
# honest purposes: (1) a fallback when a fixture has no quoted odds, and (2) a
# displayed comparison column, so material model/market divergence is visible.
MODEL_WEIGHT = 0.0
EDGE_THRESHOLD = 5.0          # percentage points above market to flag an edge
OUTCOMES = ("H", "D", "A")

DIVISION_ORDER = ["Premier League", "Championship", "League One", "League Two"]
DIVISION_SUB = {"Premier League": "Tier 1", "Championship": "Tier 2",
                "League One": "Tier 3", "League Two": "Tier 4"}


# ---------------------------------------------------------------- probabilities

def blend(model_pct, market_pct, adjust=None):
    """Blend model and market, apply any manual adjustment, renormalise to 100."""
    if market_pct is None and model_pct is None:
        return None
    if market_pct is None:
        out = dict(model_pct)
    elif model_pct is None:
        out = dict(market_pct)
    else:
        w = MODEL_WEIGHT
        out = {k: w * model_pct[k] + (1 - w) * market_pct[k] for k in OUTCOMES}
    if adjust:
        out = {k: out[k] + float(adjust.get(k, 0) or 0) for k in OUTCOMES}
    out = {k: max(0.5, out[k]) for k in OUTCOMES}
    tot = sum(out.values())
    return {k: round(100 * out[k] / tot, 1) for k in OUTCOMES}


def build_predictions(today, ratings):
    known = ratings["teams"]
    rows = []
    for fx in today["fixtures"]:
        if fx.get("postponed"):
            rows.append({**fx, "postponed": True})
            continue
        odds = fx.get("odds") or {}
        market = fe_model.devig(odds.get("H"), odds.get("D"), odds.get("A"))

        h, _ = fe_teams.resolve(fx["home"], known)
        a, _ = fe_teams.resolve(fx["away"], known)
        model_pct = fe_model.predict(ratings, h, a) if (h and a) else None

        final = blend(model_pct, market, fx.get("adjust"))
        if final is None:
            continue

        if model_pct is None:
            source = "market only (no rating for one or both clubs)"
        elif fx.get("adjust"):
            source = "model + market, with a manual adjustment"
        else:
            source = "model + market blend"

        edge_outcome = edge_odds = None
        value_flag = None
        if market:
            diffs = {k: round(final[k] - market[k], 1) for k in OUTCOMES}
            best = max(diffs, key=diffs.get)
            if diffs[best] >= EDGE_THRESHOLD:
                edge_outcome = best
                edge_odds = odds.get(best)
                label = {"H": fx["home"] + " (Home)", "D": "Draw",
                         "A": fx["away"] + " (Away)"}[best]
                value_flag = f"{label} +{diffs[best]}pp vs market"
        else:
            diffs = {k: 0.0 for k in OUTCOMES}

        rows.append({
            "league": fx["league"], "home": fx["home"], "away": fx["away"],
            "kickoff": fx.get("kickoff", ""), "odds_dec": odds,
            "market_pct": market, "model_pct_raw": model_pct, "final_pct": final,
            "diffs": diffs, "value_flag": value_flag,
            "edge_outcome": edge_outcome, "edge_odds_dec": edge_odds,
            "factors": fx.get("factors") or [], "prediction_source": source,
            "postponed": False,
        })
    return rows


# ---------------------------------------------------------------- track record

def brier(pct, actual):
    return sum(((pct[k] / 100.0) - (1.0 if k == actual else 0.0)) ** 2 for k in OUTCOMES)


def compute_metrics(log):
    finals = [m for m in log if m.get("status") == "final" and m.get("result") in OUTCOMES]
    n = len(finals)
    out = {"tracked_total": len(log), "final_count": n, "pending_count": len(log) - n}
    if n == 0:
        out.update({"brier_model": None, "brier_market": None, "hit_rate_model": None,
                    "hit_rate_market": None, "calibration": [], "by_division": {},
                    "edges": {"n": 0, "wins": 0, "staked": 0, "returned": 0,
                              "profit": 0, "roi_pct": None}})
        return out

    def top(p):
        return max(OUTCOMES, key=lambda k: p[k])

    with_mkt = [m for m in finals if m.get("market_pct")]
    out["brier_model"] = round(sum(brier(m["model_pct"], m["result"]) for m in finals) / n, 3)
    out["hit_rate_model"] = round(100 * sum(1 for m in finals if top(m["model_pct"]) == m["result"]) / n, 1)
    if with_mkt:
        k = len(with_mkt)
        out["brier_market"] = round(sum(brier(m["market_pct"], m["result"]) for m in with_mkt) / k, 3)
        out["hit_rate_market"] = round(100 * sum(1 for m in with_mkt if top(m["market_pct"]) == m["result"]) / k, 1)
    else:
        out["brier_market"] = out["hit_rate_market"] = None

    calib = []
    for lo in range(0, 100, 10):
        hi = lo + 10
        preds, hits = [], []
        for m in finals:
            for k in OUTCOMES:
                p = m["model_pct"][k]
                if lo <= p < hi or (hi == 100 and p == 100):
                    preds.append(p)
                    hits.append(1 if k == m["result"] else 0)
        if len(preds) >= 5:
            calib.append({"bin": f"{lo}-{hi}%", "mid": lo + 5,
                          "avg_predicted": round(sum(preds) / len(preds), 1),
                          "actual_freq": round(100 * sum(hits) / len(hits), 1),
                          "n": len(preds)})
    out["calibration"] = calib

    by = {}
    for m in finals:
        by.setdefault(m["league"], []).append(m)
    out["by_division"] = {
        d: {"n": len(ms),
            "brier_model": round(sum(brier(x["model_pct"], x["result"]) for x in ms) / len(ms), 3),
            "hit_rate_model": round(100 * sum(1 for x in ms if top(x["model_pct"]) == x["result"]) / len(ms), 1)}
        for d, ms in by.items()}

    eb = [m for m in finals if m.get("edge_outcome") and m.get("edge_odds_dec")]
    if eb:
        staked = len(eb)
        returned = sum(m["edge_odds_dec"] for m in eb if m["edge_outcome"] == m["result"])
        wins = sum(1 for m in eb if m["edge_outcome"] == m["result"])
        out["edges"] = {"n": staked, "wins": wins, "staked": staked,
                        "returned": round(returned, 2),
                        "profit": round(returned - staked, 2),
                        "roi_pct": round(100 * (returned - staked) / staked, 1)}
    else:
        out["edges"] = {"n": 0, "wins": 0, "staked": 0, "returned": 0, "profit": 0, "roi_pct": None}
    return out


# ---------------------------------------------------------------- rendering

def esc(s):
    return _html.escape(str(s))


def pct(v):
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def calibration_svg(calib):
    if len(calib) < 2:
        return ""
    W, H, PAD = 320, 220, 30
    fx = lambda v: PAD + (v / 100.0) * (W - 2 * PAD)
    fy = lambda v: (H - PAD) - (v / 100.0) * (H - 2 * PAD)
    grid = "".join(f'<line x1="{fx(v)}" y1="{fy(0)}" x2="{fx(v)}" y2="{fy(100)}" class="grid-line"/>'
                   f'<line x1="{fx(0)}" y1="{fy(v)}" x2="{fx(100)}" y2="{fy(v)}" class="grid-line"/>'
                   for v in (0, 25, 50, 75, 100))
    diag = f'<line x1="{fx(0)}" y1="{fy(0)}" x2="{fx(100)}" y2="{fy(100)}" class="diag-line"/>'
    pts = sorted(calib, key=lambda c: c["mid"])
    path = " ".join(f'{"M" if i == 0 else "L"}{fx(p["avg_predicted"]):.1f},{fy(p["actual_freq"]):.1f}'
                    for i, p in enumerate(pts))
    dots = "".join(f'<circle cx="{fx(p["avg_predicted"]):.1f}" cy="{fy(p["actual_freq"]):.1f}" '
                   f'r="{3 + min(6, math.sqrt(p["n"])):.1f}" class="calib-dot">'
                   f'<title>{p["bin"]}: forecast {p["avg_predicted"]}%, actual {p["actual_freq"]}% (n={p["n"]})</title></circle>'
                   for p in pts)
    labels = (f'<text x="{fx(50)}" y="{H-4}" class="axis-label" text-anchor="middle">Forecast probability</text>'
              f'<text x="10" y="{fy(50)}" class="axis-label" text-anchor="middle" '
              f'transform="rotate(-90 10 {fy(50)})">Actual frequency</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="calib-chart" role="img" '
            f'aria-label="Calibration: forecast probability versus actual frequency">'
            f'{grid}{diag}<path d="{path}" class="calib-line"/>{dots}{labels}</svg>')


def match_card(m):
    f = m["final_pct"]
    mk = m["market_pct"]
    badge = f'<span class="badge">EDGE &middot; {esc(m["value_flag"])}</span>' if m["value_flag"] else ""
    factors = ("<ul class='factors'>" + "".join(f"<li>{esc(x)}</li>" for x in m["factors"]) + "</ul>") if m["factors"] else ""
    top = max([("H", f["H"], m["home"]), ("D", f["D"], "Draw"), ("A", f["A"], m["away"])], key=lambda t: t[1])
    o = m["odds_dec"] or {}

    def row(label, key):
        od = o.get(key)
        return (f'<tr><td>{esc(label)}</td><td class="mono">{od if od else "&mdash;"}</td>'
                f'<td class="mono">{pct(mk[key]) + "%" if mk else "&mdash;"}</td>'
                f'<td class="mono">{pct(m["model_pct_raw"][key]) + "%" if m["model_pct_raw"] else "&mdash;"}</td>'
                f'<td class="mono strong">{pct(f[key])}%</td></tr>')

    return f"""
    <article class="card{' has-edge' if m['value_flag'] else ''}" data-edge="{'1' if m['value_flag'] else '0'}">
      <div class="card-top"><span class="kickoff">{esc(m['kickoff'])}</span>{badge}</div>
      <h3 class="teams"><span>{esc(m['home'])}</span><span class="vs">v</span><span>{esc(m['away'])}</span></h3>
      <div class="pick">Forecast lean: <strong>{esc(top[2])}</strong> &middot; {pct(top[1])}%</div>
      <div class="bar" role="img" aria-label="Home {pct(f['H'])}%, Draw {pct(f['D'])}%, Away {pct(f['A'])}%">
        <div class="seg seg-h" style="width:{f['H']}%"><span>{pct(f['H'])}%</span></div>
        <div class="seg seg-d" style="width:{f['D']}%"><span>{pct(f['D'])}%</span></div>
        <div class="seg seg-a" style="width:{f['A']}%"><span>{pct(f['A'])}%</span></div>
      </div>
      <div class="legend-row"><span><i class="dot dot-h"></i>Home</span><span><i class="dot dot-d"></i>Draw</span><span><i class="dot dot-a"></i>Away</span></div>
      <table class="odds-table">
        <thead><tr><th></th><th>Odds</th><th>Market</th><th>Model</th><th>Forecast</th></tr></thead>
        <tbody>{row(m['home'], 'H')}{row('Draw', 'D')}{row(m['away'], 'A')}</tbody>
      </table>
      {factors}
      <div class="source-line">{esc(m['prediction_source'])}</div>
    </article>"""


def track_section(mt):
    if mt["final_count"] == 0:
        return f"""
    <section class="division" id="track-record">
      <div class="division-head"><div class="division-title">
        <span class="division-eyebrow">Forecast accuracy over time</span><h2>Track Record</h2></div>
        <div class="division-meta">{mt['tracked_total']} logged &middot; 0 confirmed</div></div>
      <div class="callout">No fixtures have been graded yet. Once forecasts reach full time, this section
      reports calibration, Brier score against the market, hit rate, and return on flagged edges.</div>
    </section>"""
    e = mt["edges"]
    edge_txt = (f'{e["n"]} bets &middot; {e["wins"]} won &middot; profit '
                f'{"+" if e["profit"] >= 0 else ""}{e["profit"]}u') if e["n"] else "No flagged edges settled yet."
    chart = calibration_svg(mt["calibration"])
    chart_block = (f'<div class="calib-wrap">{chart}<p class="note">Every forecast probability is binned '
                   f'and plotted against how often that outcome actually occurred. Points on the dashed '
                   f'diagonal are well calibrated; above means under-confident, below means over-confident.</p></div>'
                   if chart else '<p class="note">The calibration chart appears once more matches have been graded.</p>')
    rows = "".join(f'<tr><td>{esc(d)}</td><td class="mono">{s["n"]}</td>'
                   f'<td class="mono">{s["brier_model"]}</td><td class="mono">{s["hit_rate_model"]}%</td></tr>'
                   for d, s in sorted(mt["by_division"].items(), key=lambda kv: -kv[1]["n"]))
    bm = mt["brier_market"] if mt["brier_market"] is not None else "&mdash;"
    hm = f'{mt["hit_rate_market"]}%' if mt["hit_rate_market"] is not None else "&mdash;"
    roi = f'{e["roi_pct"]}%' if e["roi_pct"] is not None else "&mdash;"
    return f"""
    <section class="division" id="track-record">
      <div class="division-head"><div class="division-title">
        <span class="division-eyebrow">Forecast accuracy over time</span><h2>Track Record</h2></div>
        <div class="division-meta">{mt['tracked_total']} logged &middot; {mt['final_count']} confirmed &middot; {mt['pending_count']} pending</div></div>
      <div class="track-grid">
        <div class="track-stats">
          <div class="tstat"><div class="tnum mono">{mt['brier_model']}</div><div class="tlabel">Brier score (lower is better)<br><span class="vs-market">market {bm}</span></div></div>
          <div class="tstat"><div class="tnum mono">{mt['hit_rate_model']}%</div><div class="tlabel">Top-pick hit rate<br><span class="vs-market">market {hm}</span></div></div>
          <div class="tstat"><div class="tnum mono">{roi}</div><div class="tlabel">Flagged-edge ROI<br><span class="vs-market">{edge_txt}</span></div></div>
        </div>
        {chart_block}
      </div>
      <table class="odds-table division-table">
        <thead><tr><th>Division</th><th>Graded</th><th>Brier</th><th>Hit rate</th></tr></thead>
        <tbody>{rows}</tbody></table>
    </section>"""


CSS = """
:root{color-scheme:light;--bg:#EEF1EC;--surface:#fff;--surface-2:#F5F7F3;--text-primary:#171B18;
--text-secondary:#53594F;--text-muted:#7C8276;--border:#DCE1D6;--claret:#7A2036;--claret-ink:#5E1829;
--claret-soft:#F3E4E8;--home:#2a78d6;--draw:#eb6834;--away:#1baf7a;
--shadow:0 1px 2px rgba(23,27,24,.06),0 6px 20px -8px rgba(23,27,24,.12)}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;--bg:#12161A;--surface:#1A211F;
--surface-2:#1F2724;--text-primary:#F1F4EF;--text-secondary:#ABB3A5;--text-muted:#7E877C;--border:#2B332E;
--claret:#D97392;--claret-ink:#F0A6BB;--claret-soft:#341C24;--home:#3987e5;--draw:#d95926;--away:#199e70;
--shadow:0 1px 2px rgba(0,0,0,.3),0 10px 24px -10px rgba(0,0,0,.5)}}
:root[data-theme=dark]{color-scheme:dark;--bg:#12161A;--surface:#1A211F;--surface-2:#1F2724;--text-primary:#F1F4EF;
--text-secondary:#ABB3A5;--text-muted:#7E877C;--border:#2B332E;--claret:#D97392;--claret-ink:#F0A6BB;
--claret-soft:#341C24;--home:#3987e5;--draw:#d95926;--away:#199e70;
--shadow:0 1px 2px rgba(0,0,0,.3),0 10px 24px -10px rgba(0,0,0,.5)}
*{box-sizing:border-box}html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--text-primary);font-family:"Public Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}
.mono{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
h1,h2,h3{font-family:"Big Shoulders Display","Arial Narrow",sans-serif;font-weight:700;margin:0;text-wrap:balance}
a{color:var(--claret)}
.top{position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px solid var(--border);padding:20px clamp(16px,4vw,40px) 14px}
.top-row{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
.brand-eyebrow{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--claret)}
.brand h1{font-size:clamp(30px,5vw,44px);line-height:.95}
.date-line{font-size:13px;color:var(--text-secondary)}
.summary-stats{display:flex;gap:22px;flex-wrap:wrap}.stat{text-align:right}
.stat .num{font-family:"Big Shoulders Display",sans-serif;font-size:28px;line-height:1}
.stat .label{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted)}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.pill{font-size:13px;text-decoration:none;color:var(--text-secondary);border:1px solid var(--border);border-radius:999px;padding:6px 12px;display:inline-flex;align-items:center;gap:6px}
.pill:hover{border-color:var(--claret);color:var(--claret)}.pill-track{border-style:dashed}
.pill-count{font-family:"JetBrains Mono",monospace;font-size:11px;background:var(--surface-2);padding:1px 6px;border-radius:999px;color:var(--text-muted)}
.filter-row{margin-top:12px;font-size:13px;color:var(--text-secondary)}
.filter-row label{display:flex;align-items:center;gap:7px;cursor:pointer}
main{padding:8px clamp(16px,4vw,40px) 60px;max-width:1240px;margin:0 auto}
.callout{background:var(--surface-2);border:1px solid var(--border);border-left:3px solid var(--claret);padding:10px 14px;border-radius:4px;font-size:13px;color:var(--text-secondary);margin:18px 0}
.division{margin-top:44px}
.division-head{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;border-bottom:2px solid var(--claret);padding-bottom:8px;margin-bottom:18px}
.division-eyebrow{font-family:"JetBrains Mono",monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--claret);display:block;margin-bottom:2px}
.division-title h2{font-size:clamp(24px,3.4vw,32px)}.division-meta{font-size:12px;color:var(--text-muted)}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:10px}
.card.has-edge{border-color:var(--claret)}
.card-top{display:flex;justify-content:space-between;align-items:center}
.kickoff{font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--text-muted)}
.badge{font-family:"JetBrains Mono",monospace;font-size:10.5px;background:var(--claret-soft);color:var(--claret-ink);border-radius:999px;padding:3px 9px}
.teams{font-size:21px;line-height:1.1;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.vs{font-family:"Public Sans",sans-serif;font-weight:400;font-size:13px;color:var(--text-muted)}
.pick{font-size:13px;color:var(--text-secondary)}.pick strong{color:var(--text-primary)}
.bar{display:flex;height:26px;border-radius:5px;overflow:hidden;border:1px solid var(--border)}
.seg{display:flex;align-items:center;justify-content:center;min-width:0;overflow:hidden}
.seg span{font-family:"JetBrains Mono",monospace;font-size:11px;color:#fff;text-shadow:0 1px 1px rgba(0,0,0,.25);white-space:nowrap}
.seg-h{background:var(--home)}.seg-d{background:var(--draw)}.seg-a{background:var(--away)}
.legend-row{display:flex;gap:14px;font-size:11.5px;color:var(--text-muted)}
.legend-row span{display:inline-flex;align-items:center;gap:5px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot-h{background:var(--home)}.dot-d{background:var(--draw)}.dot-a{background:var(--away)}
.odds-table{width:100%;border-collapse:collapse;font-size:12.5px}
.odds-table th{text-align:right;font-weight:500;color:var(--text-muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;padding-bottom:4px}
.odds-table th:first-child,.odds-table td:first-child{text-align:left}
.odds-table td{text-align:right;padding:3px 0;color:var(--text-secondary);border-top:1px solid var(--border)}
.odds-table td:first-child{color:var(--text-primary)}.odds-table td.strong{color:var(--text-primary);font-weight:600}
.note{font-size:11.5px;color:var(--text-muted);font-style:italic}
.factors{margin:0;padding-left:18px;font-size:12.5px;color:var(--text-secondary);display:flex;flex-direction:column;gap:4px}
.factors li::marker{color:var(--claret)}
.source-line{font-size:10.5px;color:var(--text-muted);border-top:1px dashed var(--border);padding-top:8px}
.track-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;align-items:start}
@media(max-width:760px){.track-grid{grid-template-columns:1fr}}
.track-stats{display:flex;flex-direction:column;gap:14px}
.tstat{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 14px;display:flex;align-items:baseline;gap:12px}
.tnum{font-family:"Big Shoulders Display",sans-serif;font-size:30px;min-width:74px}
.tlabel{font-size:12px;color:var(--text-secondary);line-height:1.4}
.vs-market{color:var(--text-muted);font-size:11px}
.calib-wrap{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px}
.calib-chart{width:100%;height:auto;overflow:visible}
.grid-line{stroke:var(--border);stroke-width:1}
.diag-line{stroke:var(--text-muted);stroke-width:1.5;stroke-dasharray:4 4}
.calib-line{fill:none;stroke:var(--claret);stroke-width:2}
.calib-dot{fill:var(--claret);stroke:var(--surface);stroke-width:1.5}
.axis-label{font-family:"JetBrains Mono",monospace;font-size:8px;fill:var(--text-muted)}
.division-table{margin-top:4px}
footer{max-width:1240px;margin:0 auto;padding:20px clamp(16px,4vw,40px) 60px;color:var(--text-muted);font-size:12px;border-top:1px solid var(--border)}
footer h3{font-size:15px;color:var(--text-secondary);margin-bottom:6px}footer p{max-width:65ch}
.card[data-edge="0"].filtered-hide{display:none}
"""


def render(date_str, rows, mt, log, notes=""):
    by_div = {d: [] for d in DIVISION_ORDER}
    for r in rows:
        if not r.get("postponed"):
            by_div.setdefault(r["league"], []).append(r)

    sections = ""
    for d in DIVISION_ORDER:
        ms = by_div.get(d) or []
        if not ms:
            continue
        edges = sum(1 for m in ms if m["value_flag"])
        sections += f"""
    <section class="division" id="{d.lower().replace(' ', '-')}">
      <div class="division-head"><div class="division-title">
        <span class="division-eyebrow">{DIVISION_SUB.get(d,'')}</span><h2>{esc(d)}</h2></div>
        <div class="division-meta">{len(ms)} fixture{'s' if len(ms)!=1 else ''} &middot; {edges} flagged edge{'s' if edges!=1 else ''}</div></div>
      <div class="card-grid">{''.join(match_card(m) for m in ms)}</div>
    </section>"""
    sections += track_section(mt)

    played = [r for r in rows if not r.get("postponed")]
    total_edges = sum(1 for r in played if r["value_flag"])
    pp = [r for r in rows if r.get("postponed")]
    pp_note = ("<div class='callout'><strong>Postponed:</strong> " +
               ", ".join(f"{esc(r['home'])} v {esc(r['away'])} ({esc(r['league'])})" for r in pp) +
               " &mdash; excluded from today's board.</div>") if pp else ""
    no_fx = "<div class='callout'><strong>No fixtures today</strong> across the Premier League, Championship, League One or League Two. The Track Record below still reflects all previously graded forecasts.</div>" if not played else ""
    notes_html = f"<div class='callout'>{esc(notes)}</div>" if notes else ""

    nav = "".join(f'<a href="#{d.lower().replace(" ","-")}" class="pill">{esc(d)} '
                  f'<span class="pill-count">{len(by_div.get(d) or [])}</span></a>'
                  for d in DIVISION_ORDER if by_div.get(d))
    nav += '<a href="#track-record" class="pill pill-track">Track Record</a>'

    stamp = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    return f"""<title>Fixture Edge</title>
<style>{CSS}</style>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700;800&family=Public+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap">
<div class="top">
  <div class="top-row">
    <div class="brand">
      <span class="brand-eyebrow">English Football &middot; Match Day Probabilities</span>
      <h1>Fixture Edge</h1>
      <span class="date-line">{esc(date_str)}</span>
    </div>
    <div class="summary-stats">
      <div class="stat"><div class="num mono">{len(played)}</div><div class="label">Fixtures</div></div>
      <div class="stat"><div class="num mono">{total_edges}</div><div class="label">Flagged edges</div></div>
      <div class="stat"><div class="num mono">{mt['final_count']}</div><div class="label">Graded to date</div></div>
    </div>
  </div>
  <nav class="nav">{nav}</nav>
  <div class="filter-row"><label><input type="checkbox" id="edge-filter"> Show flagged edges only</label></div>
</div>
<main>{no_fx}{pp_note}{notes_html}{sections}</main>
<footer>
  <h3>Methodology, and what this tool does not claim</h3>
  <p>The headline probability for each fixture is the de-vigged best available UK bookmaker price &mdash;
  the overround stripped out proportionally so the three outcomes sum to 100%. It is shown as the forecast
  because the evidence says it is the best forecast available.</p>
  <p>A Dixon-Coles model is also computed and shown alongside it: attack and defence ratings fitted to four
  seasons of results across all four English divisions on one shared scale, with time-decay weighting and a
  home-advantage term. It is displayed for comparison, and used as a fallback when a fixture has no quoted
  price. It is deliberately given <strong>zero weight</strong> in the forecast. A walk-forward backtest over
  5,103 out-of-sample matches swept the model's blend weight from 0 to 100%: accuracy was best at zero and
  got monotonically worse with every increase (Brier 0.6126 at 0% model, 0.6255 at 100%). Closing odds
  absorb team news, line-ups and sharp money that a goals-based model never sees.</p>
  <p><strong>What that means for "edges".</strong> Because the forecast starts from the market, an outcome is
  only flagged when researched team news &mdash; an injury, a suspension, rotation risk before a midweek
  cup tie &mdash; gives a concrete reason to move off the price, by {EDGE_THRESHOLD:.0f} percentage points
  or more. Those flags are the one place this tool tries to add something the morning price may not have
  absorbed yet, and the Track Record section is the honest scoreboard for whether they ever actually pay.
  Where the model simply disagrees with the market, that shows in the comparison column and is not dressed
  up as a betting signal. Nothing here is a tip, and no claim is made that this beats the bookmakers.</p>
  <p>Generated {stamp}. Odds and team news move quickly &mdash; this is a morning snapshot, not a live feed.</p>
</footer>
<script type="application/json" id="fixture-edge-log">{json.dumps(log, separators=(',', ':'))}</script>
<script>
(function(){{var cb=document.getElementById('edge-filter'),cards=document.querySelectorAll('.card');
cb.addEventListener('change',function(){{cards.forEach(function(c){{
if(cb.checked){{c.classList.toggle('filtered-hide',c.getAttribute('data-edge')==='0');}}
else{{c.classList.remove('filtered-hide');}}}});}});}})();
</script>"""


# ---------------------------------------------------------------- entry point

def main():
    if len(sys.argv) < 6:
        print(__doc__)
        sys.exit(1)
    today_p, log_p, ratings_p, out_p, newlog_p = sys.argv[1:6]

    today = json.load(open(today_p))
    ratings = json.load(open(ratings_p))
    try:
        log = json.load(open(log_p))
        if not isinstance(log, list):
            log = []
    except Exception:
        log = []

    rows = build_predictions(today, ratings)

    date_str = today["date"]
    existing = {m["id"] for m in log if isinstance(m, dict) and "id" in m}
    for r in rows:
        if r.get("postponed"):
            continue
        rid = f'{date_str}|{r["league"]}|{r["home"]}|{r["away"]}'
        if rid in existing:
            continue
        log.append({
            "id": rid, "date": date_str, "league": r["league"], "home": r["home"],
            "away": r["away"], "kickoff": r["kickoff"], "model_pct": r["final_pct"],
            "model_raw_pct": r["model_pct_raw"], "market_pct": r["market_pct"],
            "odds_dec": r["odds_dec"], "value_flag": r["value_flag"],
            "edge_outcome": r["edge_outcome"], "edge_odds_dec": r["edge_odds_dec"],
            "status": "pending", "result": None, "score": None,
        })

    mt = compute_metrics(log)
    try:
        pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %-d %B %Y")
    except Exception:
        pretty = date_str

    html_out = render(pretty, rows, mt, log, today.get("notes", ""))
    open(out_p, "w").write(html_out)
    json.dump(log, open(newlog_p, "w"), indent=1)
    print(f"wrote {out_p} ({len(html_out)} bytes) | fixtures {len(rows)} | log {len(log)} | graded {mt['final_count']}")


if __name__ == "__main__":
    main()
