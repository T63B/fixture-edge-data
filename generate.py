#!/usr/bin/env python3
"""
Fixture Edge — deterministic dashboard builder.

Usage:  python3 generate.py today.json log.json ratings.json out.html new_log.json

WHAT THE FORECAST IS
--------------------
The headline forecast is THIS TOOL'S OWN MODEL: Dixon-Coles attack and defence
ratings fitted across all four English divisions on one shared scale, blending a
goals-based and a shots-on-target-based fit. The bookmaker price is shown beside
it as a benchmark, NOT as the answer.

That is a deliberate reversal of the earlier design, which published the de-vigged
market price as the forecast. That version could not identify value against the
odds, because its forecast *was* the odds -- it had no opinion of its own.

WHAT THAT COSTS, STATED PLAINLY
-------------------------------
On walk-forward backtesting over 5,103 out-of-sample matches:

    model (goals + shots blend)   Brier 0.6249   hit rate 47.3%
    market (de-vigged best price) Brier 0.6126   hit rate 49.1%

The market is the better forecaster. Publishing the model means publishing the
less accurate of the two, knowingly, in exchange for having an independent view
that can be measured and improved. Divergence between the two is the tool's
output -- it is NOT evidence of betting value, and must never be presented as such.

STALENESS IS THE LARGEST ERROR SOURCE. The model's gap to the market roughly
doubles as ratings age (+0.011 when fresh, +0.018 at 90-150 days). Run
fit_model.py regularly; it matters ~24x more than any structural tweak tested.

today.json schema:
{
  "date": "2026-09-19",
  "fixtures": [
    {"league": "Premier League", "home": "Liverpool", "away": "Nottingham Forest",
     "kickoff": "12:30",
     "odds": {"H": 1.44, "D": 5.0, "A": 6.5},      # decimal, best available
     "adjust": {"H": 2.0, "D": -1.0, "A": -1.0},   # optional, percentage points
     "factors": ["injury note", "form note"],       # optional
     "postponed": false}
  ],
  "notes": "optional caveat shown at the top"
}
"""

import html as _html
import json
import math
import re
import sys
from datetime import datetime, timezone

import model2 as fe_model
import teams as fe_teams

DIVERGENCE_PP = 10.0      # flag when model and market differ this much on any outcome
OUTCOMES = ("H", "D", "A")
DIVISION_ORDER = ["Premier League", "Championship", "League One", "League Two"]
DIVISION_SUB = {"Premier League": "Tier 1", "Championship": "Tier 2",
                "League One": "Tier 3", "League Two": "Tier 4"}


# ---------------------------------------------------------------- probabilities

def normalise(p):
    p = {k: max(0.3, p[k]) for k in OUTCOMES}
    t = sum(p.values())
    return {k: round(100 * p[k] / t, 1) for k in OUTCOMES}


def build_predictions(today, ratings):
    known = ratings.get("teams", [])
    sot = ratings.get("sot")
    wgt = ratings.get("blend_weight", 1.0)
    rows = []
    for fx in today["fixtures"]:
        if fx.get("postponed"):
            rows.append({**fx, "postponed": True})
            continue

        odds = fx.get("odds") or {}
        market = fe_model.devig(odds.get("H"), odds.get("D"), odds.get("A"))
        if market:
            market = {k: round(market[k], 1) for k in OUTCOMES}

        h, _ = fe_teams.resolve(fx["home"], known)
        a, _ = fe_teams.resolve(fx["away"], known)
        model = None
        if h and a:
            raw = fe_model.predict(ratings, h, a, blend_with=sot, weight=wgt)
            if raw:
                model = {k: round(raw[k], 1) for k in OUTCOMES}

        # The forecast IS the model. Fall back to the market only when the model
        # cannot price the fixture at all (a club with no rating -- typically one
        # just promoted from the National League).
        if model:
            final = dict(model)
            source = "model (goals + shots ratings)"
            if fx.get("adjust"):
                final = normalise({k: final[k] + float(fx["adjust"].get(k, 0) or 0)
                                   for k in OUTCOMES})
                source = "model, adjusted for researched team news"
        elif market:
            final = dict(market)
            source = "market price (no rating for one or both clubs)"
        else:
            continue

        diffs = ({k: round(final[k] - market[k], 1) for k in OUTCOMES}
                 if market else {k: 0.0 for k in OUTCOMES})
        flag = None
        if market and model:
            worst = max(diffs, key=lambda k: abs(diffs[k]))
            if abs(diffs[worst]) >= DIVERGENCE_PP:
                label = {"H": fx["home"], "D": "Draw", "A": fx["away"]}[worst]
                direction = "above" if diffs[worst] > 0 else "below"
                flag = f"{label} {abs(diffs[worst]):.0f}pp {direction} market"

        rows.append({
            "league": fx["league"], "home": fx["home"], "away": fx["away"],
            "kickoff": fx.get("kickoff", ""), "odds_dec": odds,
            "market_pct": market, "model_pct_raw": model, "final_pct": final,
            "diffs": diffs, "value_flag": flag,
            "edge_outcome": None, "edge_odds_dec": None,
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
    keys_empty = {
        "brier_model": None, "brier_market": None, "hit_rate_model": None,
        "hit_rate_market": None, "calibration": [], "by_division": {},
        "compare_n": 0, "odds_coverage_pct": 0, "brier_model_all": None,
        "closing_n": 0, "brier_close": None, "brier_at_close_subset": None,
        "timing_cost": None, "mean_drift": None, "clv_n": 0, "clv_mean": None,
        "clv_positive": 0, "diverge_n": 0, "diverge_model_brier": None,
        "diverge_market_brier": None, "diverge_model_hit": None,
        "diverge_market_hit": None,
        "edges": {"n": 0, "wins": 0, "staked": 0, "returned": 0, "profit": 0, "roi_pct": None},
    }
    if n == 0:
        out.update(keys_empty)
        return out
    out.update(keys_empty)

    def top(p):
        return max(OUTCOMES, key=lambda k: p[k])

    # Model and market are only comparable on fixtures carrying both.
    with_mkt = [m for m in finals if m.get("market_pct")]
    out["compare_n"] = len(with_mkt)
    out["odds_coverage_pct"] = round(100 * len(with_mkt) / n, 1)
    out["brier_model_all"] = round(sum(brier(m["model_pct"], m["result"]) for m in finals) / n, 3)

    if with_mkt:
        k = len(with_mkt)
        out["brier_model"] = round(sum(brier(m["model_pct"], m["result"]) for m in with_mkt) / k, 3)
        out["brier_market"] = round(sum(brier(m["market_pct"], m["result"]) for m in with_mkt) / k, 3)
        out["hit_rate_model"] = round(100 * sum(1 for m in with_mkt if top(m["model_pct"]) == m["result"]) / k, 1)
        out["hit_rate_market"] = round(100 * sum(1 for m in with_mkt if top(m["market_pct"]) == m["result"]) / k, 1)
    else:
        out["brier_model"] = out["brier_model_all"]
        out["hit_rate_model"] = round(100 * sum(1 for m in finals if top(m["model_pct"]) == m["result"]) / n, 1)

    # Where the model disagreed loudly, who was right? This is the question the
    # whole independent-forecast design exists to answer.
    div = [m for m in with_mkt
           if max(abs(m["model_pct"][k] - m["market_pct"][k]) for k in OUTCOMES) >= DIVERGENCE_PP]
    out["diverge_n"] = len(div)
    if div:
        d = len(div)
        out["diverge_model_brier"] = round(sum(brier(m["model_pct"], m["result"]) for m in div) / d, 3)
        out["diverge_market_brier"] = round(sum(brier(m["market_pct"], m["result"]) for m in div) / d, 3)
        out["diverge_model_hit"] = round(100 * sum(1 for m in div if top(m["model_pct"]) == m["result"]) / d, 1)
        out["diverge_market_hit"] = round(100 * sum(1 for m in div if top(m["market_pct"]) == m["result"]) / d, 1)

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

    # closing-price comparison (populated by enrich_closing.py)
    withclose = [m for m in finals if m.get("close_pct")]
    out["closing_n"] = len(withclose)
    if withclose:
        k = len(withclose)
        out["brier_close"] = round(sum(brier(m["close_pct"], m["result"]) for m in withclose) / k, 3)
        out["brier_at_close_subset"] = round(sum(brier(m["model_pct"], m["result"]) for m in withclose) / k, 3)
        out["timing_cost"] = round(out["brier_at_close_subset"] - out["brier_close"], 3)
        drifts = [m["drift"] for m in withclose if m.get("drift")]
        out["mean_drift"] = (round(sum(sum(abs(v) for v in d.values()) / 3 for d in drifts) / len(drifts), 2)
                             if drifts else None)

    eb = [m for m in finals if m.get("edge_outcome") and m.get("edge_odds_dec")]
    if eb:
        staked = len(eb)
        returned = sum(m["edge_odds_dec"] for m in eb if m["edge_outcome"] == m["result"])
        wins = sum(1 for m in eb if m["edge_outcome"] == m["result"])
        out["edges"] = {"n": staked, "wins": wins, "staked": staked,
                        "returned": round(returned, 2), "profit": round(returned - staked, 2),
                        "roi_pct": round(100 * (returned - staked) / staked, 1)}
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
    md = m["model_pct_raw"]
    badge = (f'<span class="badge">MODEL {esc(m["value_flag"])}</span>' if m["value_flag"] else "")
    factors = ("<ul class='factors'>" + "".join(f"<li>{esc(x)}</li>" for x in m["factors"]) + "</ul>"
               if m["factors"] else "")
    top = max([("H", f["H"], m["home"]), ("D", f["D"], "Draw"), ("A", f["A"], m["away"])],
              key=lambda t: t[1])
    o = m["odds_dec"] or {}

    def row(label, key):
        od = o.get(key)
        return (f'<tr><td>{esc(label)}</td>'
                f'<td class="mono strong">{pct(f[key])}%</td>'
                f'<td class="mono">{pct(mk[key]) + "%" if mk else "&mdash;"}</td>'
                f'<td class="mono">{od if od else "&mdash;"}</td></tr>')

    return f"""
    <article class="card{' has-edge' if m['value_flag'] else ''}" data-edge="{'1' if m['value_flag'] else '0'}">
      <div class="card-top"><span class="kickoff">{esc(m['kickoff'])}</span>{badge}</div>
      <h3 class="teams"><span>{esc(m['home'])}</span><span class="vs">v</span><span>{esc(m['away'])}</span></h3>
      <div class="pick">Forecast: <strong>{esc(top[2])}</strong> &middot; {pct(top[1])}%</div>
      <div class="bar" role="img" aria-label="Home {pct(f['H'])}%, Draw {pct(f['D'])}%, Away {pct(f['A'])}%">
        <div class="seg seg-h" style="width:{f['H']}%"><span>{pct(f['H'])}%</span></div>
        <div class="seg seg-d" style="width:{f['D']}%"><span>{pct(f['D'])}%</span></div>
        <div class="seg seg-a" style="width:{f['A']}%"><span>{pct(f['A'])}%</span></div>
      </div>
      <div class="legend-row"><span><i class="dot dot-h"></i>Home</span><span><i class="dot dot-d"></i>Draw</span><span><i class="dot dot-a"></i>Away</span></div>
      <table class="odds-table">
        <thead><tr><th></th><th>Forecast</th><th>Market</th><th>Odds</th></tr></thead>
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
      <div class="callout">No fixtures graded yet. Once forecasts reach full time this section reports
      calibration, the model's Brier score against the market's, and how the two compare on the fixtures
      where they disagreed most.</div>
    </section>"""

    bm = mt["brier_market"] if mt["brier_market"] is not None else "&mdash;"
    hm = f'{mt["hit_rate_market"]}%' if mt["hit_rate_market"] is not None else "&mdash;"
    verdict = ""
    if mt["brier_market"] is not None and mt["brier_model"] is not None:
        gap = mt["brier_model"] - mt["brier_market"]
        verdict = (f'<span class="vs-market">model is {abs(gap):.3f} '
                   f'{"behind" if gap > 0 else "ahead of"} the market</span>')

    # the divergence panel -- the question this design exists to answer
    if mt["diverge_n"]:
        d = mt
        who = ("the model" if d["diverge_model_brier"] < d["diverge_market_brier"] else "the market")
        div_block = (
            f'<div class="callout"><strong>When the model disagreed loudly ({d["diverge_n"]} fixtures, '
            f'{DIVERGENCE_PP:.0f}pp or more apart).</strong> Model Brier {d["diverge_model_brier"]} '
            f'against the market\'s {d["diverge_market_brier"]}; top-pick hit rate '
            f'{d["diverge_model_hit"]}% against {d["diverge_market_hit"]}%. On these fixtures '
            f'<strong>{who}</strong> was the better forecaster. This is the sharpest test of whether an '
            f'independent view adds anything &mdash; it is where the two opinions actually differ.</div>')
    else:
        div_block = ('<p class="note">No graded fixture has yet seen the model and the market disagree by '
                     f'{DIVERGENCE_PP:.0f} points or more.</p>')

    chart = calibration_svg(mt["calibration"])
    coverage = (f'<p class="note">Model and market are scored on the same {mt.get("compare_n", 0)} '
                f'fixtures &mdash; those with odds. Across all {mt["final_count"]} graded fixtures the '
                f'model scores {mt["brier_model_all"]}.</p>')
    chart_block = (f'<div class="calib-wrap">{chart}<p class="note">Every forecast probability binned '
                   f'against how often that outcome occurred. Points on the dashed diagonal are well '
                   f'calibrated; above means under-confident, below over-confident.</p>{coverage}</div>'
                   if chart else f'<div class="calib-wrap">{coverage}</div>')

    rows = "".join(f'<tr><td>{esc(d)}</td><td class="mono">{s["n"]}</td>'
                   f'<td class="mono">{s["brier_model"]}</td><td class="mono">{s["hit_rate_model"]}%</td></tr>'
                   for d, s in sorted(mt["by_division"].items(), key=lambda kv: -kv[1]["n"]))

    closing = ""
    if mt.get("closing_n"):
        cost = mt.get("timing_cost")
        ct = ("&mdash;" if cost is None else
              (f"the closing price scored {cost:+.3f} better" if cost > 0
               else f"the 07:00 forecast scored {abs(cost):.3f} better"))
        closing = (f'<p class="note"><strong>Timing:</strong> across {mt["closing_n"]} fixtures with '
                   f'archived closing odds, {ct}. Average market movement between morning and kick-off: '
                   f'{mt.get("mean_drift")} points per outcome.</p>')

    return f"""
    <section class="division" id="track-record">
      <div class="division-head"><div class="division-title">
        <span class="division-eyebrow">Forecast accuracy over time</span><h2>Track Record</h2></div>
        <div class="division-meta">{mt['tracked_total']} logged &middot; {mt['final_count']} confirmed &middot; {mt['pending_count']} pending &middot; odds found for {mt.get('odds_coverage_pct', 0)}% of graded fixtures</div></div>
      <div class="track-grid">
        <div class="track-stats">
          <div class="tstat"><div class="tnum mono">{mt['brier_model']}</div><div class="tlabel">Model Brier (lower is better)<br><span class="vs-market">market {bm} &middot; same {mt.get('compare_n', 0)} fixtures</span></div></div>
          <div class="tstat"><div class="tnum mono">{mt['hit_rate_model']}%</div><div class="tlabel">Model top-pick hit rate<br><span class="vs-market">market {hm}</span></div></div>
          <div class="tstat"><div class="tnum mono">{mt['diverge_n']}</div><div class="tlabel">Graded fixtures where model and market disagreed by {DIVERGENCE_PP:.0f}pp+<br>{verdict}</div></div>
        </div>
        {chart_block}
      </div>
      {div_block}
      {closing}
      <table class="odds-table division-table">
        <thead><tr><th>Division</th><th>Graded</th><th>Model Brier</th><th>Hit rate</th></tr></thead>
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
.card-top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.kickoff{font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--text-muted)}
.badge{font-family:"JetBrains Mono",monospace;font-size:10.5px;background:var(--claret-soft);color:var(--claret-ink);border-radius:999px;padding:3px 9px;white-space:nowrap}
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


def render(date_str, rows, mt, log, notes="", ratings=None):
    by_div = {d: [] for d in DIVISION_ORDER}
    for r in rows:
        if not r.get("postponed"):
            by_div.setdefault(r["league"], []).append(r)

    sections = ""
    for d in DIVISION_ORDER:
        ms = by_div.get(d) or []
        if not ms:
            continue
        flags = sum(1 for m in ms if m["value_flag"])
        sections += f"""
    <section class="division" id="{d.lower().replace(' ', '-')}">
      <div class="division-head"><div class="division-title">
        <span class="division-eyebrow">{DIVISION_SUB.get(d,'')}</span><h2>{esc(d)}</h2></div>
        <div class="division-meta">{len(ms)} fixture{'s' if len(ms)!=1 else ''} &middot; {flags} disagree with market by {DIVERGENCE_PP:.0f}pp+</div></div>
      <div class="card-grid">{''.join(match_card(m) for m in ms)}</div>
    </section>"""
    sections += track_section(mt)

    played = [r for r in rows if not r.get("postponed")]
    total_flags = sum(1 for r in played if r["value_flag"])
    pp = [r for r in rows if r.get("postponed")]
    pp_note = ("<div class='callout'><strong>Postponed:</strong> " +
               ", ".join(f"{esc(r['home'])} v {esc(r['away'])} ({esc(r['league'])})" for r in pp) +
               " &mdash; excluded from today's board.</div>") if pp else ""
    no_fx = ("<div class='callout'><strong>No fixtures today</strong> across the four English divisions. "
             "The Track Record below still reflects all previously graded forecasts.</div>"
             if not played else "")
    notes_html = f"<div class='callout'>{esc(notes)}</div>" if notes else ""

    stale = ""
    if ratings and ratings.get("fitted_on"):
        try:
            age = (datetime.now(timezone.utc).date()
                   - datetime.strptime(ratings["fitted_on"], "%Y-%m-%d").date()).days
            if age > 21:
                stale = (f"<div class='callout'><strong>Ratings are {age} days old.</strong> "
                         f"The model's accuracy decays materially as ratings age &mdash; its gap to the "
                         f"market roughly doubles between fresh and three months stale. Run fit_model.py.</div>")
        except Exception:
            pass

    nav = "".join(f'<a href="#{d.lower().replace(" ","-")}" class="pill">{esc(d)} '
                  f'<span class="pill-count">{len(by_div.get(d) or [])}</span></a>'
                  for d in DIVISION_ORDER if by_div.get(d))
    nav += '<a href="#track-record" class="pill pill-track">Track Record</a>'

    stamp = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    fit_line = ""
    if ratings and ratings.get("fitted_on"):
        fit_line = (f' Ratings fitted on data to {esc(ratings["fitted_on"])}'
                    f' from {ratings.get("n_matches", "?")} matches.')

    return f"""<title>Fixture Edge</title>
<style>{CSS}</style>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700;800&family=Public+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap">
<div class="top">
  <div class="top-row">
    <div class="brand">
      <span class="brand-eyebrow">English Football &middot; Independent Match Forecasts</span>
      <h1>Fixture Edge</h1>
      <span class="date-line">{esc(date_str)}</span>
    </div>
    <div class="summary-stats">
      <div class="stat"><div class="num mono">{len(played)}</div><div class="label">Fixtures</div></div>
      <div class="stat"><div class="num mono">{total_flags}</div><div class="label">Disagree with market</div></div>
      <div class="stat"><div class="num mono">{mt['final_count']}</div><div class="label">Graded to date</div></div>
    </div>
  </div>
  <nav class="nav">{nav}</nav>
  <div class="filter-row"><label><input type="checkbox" id="edge-filter"> Show only fixtures where the model disagrees with the market</label></div>
</div>
<main>{stale}{no_fx}{pp_note}{notes_html}{sections}</main>
<footer>
  <h3>What this forecast is, and what it is not</h3>
  <p>The headline probability for each fixture is <strong>this tool's own model</strong>: Dixon-Coles
  attack and defence ratings fitted across all four English divisions on one shared scale, combining a
  goals-based and a shots-on-target-based fit, with exponential time-decay weighting and a home-advantage
  term.{fit_line} The bookmaker price sits beside it as a benchmark, not as the answer.</p>
  <p><strong>The market is the more accurate forecaster, and this tool publishes the other one.</strong>
  On walk-forward backtesting over 5,103 out-of-sample matches the model scored a Brier of 0.6249 against
  the de-vigged market's 0.6126, picking the right outcome 47.3% of the time against 49.1%. That gap is
  the price of having an independent opinion: one that can be measured, criticised and improved, rather
  than a restatement of the odds. Where the model disagrees with the market, that disagreement is the
  tool's output &mdash; it is <em>not</em> a betting signal, and the Track Record above is the honest
  scoreboard for who tends to be right when the two part company.</p>
  <p>Nothing here is a tip, and no claim is made that this beats the bookmakers. Generated {stamp}.</p>
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

    def fixture_key(date, league, home, away):
        known = ratings.get("teams", [])

        def canon(name):
            r, _ = fe_teams.resolve(name, known)
            if r:
                return r.lower()
            n = re.sub(r"[^a-z0-9 ]", "", str(name).lower()).strip()
            n = re.sub(r"\s+(fc|afc|town|city|united|rovers|wanderers|athletic|county|albion)$", "", n)
            return re.sub(r"\s+", "", n)

        return f"{date}|{re.sub(r'[^a-z0-9]', '', str(league).lower())}|{canon(home)}|{canon(away)}"

    existing = set()
    for m in log:
        if isinstance(m, dict) and m.get("date"):
            existing.add(fixture_key(m["date"], m.get("league", ""), m.get("home", ""), m.get("away", "")))

    for r in rows:
        if r.get("postponed"):
            continue
        rid = fixture_key(date_str, r["league"], r["home"], r["away"])
        if rid in existing:
            continue
        existing.add(rid)
        log.append({
            "id": rid, "date": date_str, "league": r["league"], "home": r["home"],
            "away": r["away"], "kickoff": r["kickoff"], "model_pct": r["final_pct"],
            "model_raw_pct": r["model_pct_raw"], "market_pct": r["market_pct"],
            "odds_dec": r["odds_dec"], "value_flag": r["value_flag"],
            "edge_outcome": None, "edge_odds_dec": None,
            "status": "pending", "result": None, "score": None,
        })

    mt = compute_metrics(log)
    try:
        pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %-d %B %Y")
    except Exception:
        pretty = date_str

    html_out = render(pretty, rows, mt, log, today.get("notes", ""), ratings)
    open(out_p, "w").write(html_out)
    json.dump(log, open(newlog_p, "w"), indent=1)
    print(f"wrote {out_p} ({len(html_out)} bytes) | fixtures {len(rows)} | log {len(log)} "
          f"| graded {mt['final_count']} | disagreements today {sum(1 for r in rows if r.get('value_flag'))}")


if __name__ == "__main__":
    main()
