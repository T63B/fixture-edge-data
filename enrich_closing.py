#!/usr/bin/env python3
"""
Attach opening and closing odds to graded fixtures, from football-data.co.uk.

WHY: the dashboard forecasts at 07:00 from morning prices, but the closing price
is the sharper number and is what BACKTEST.md's benchmark was built on. Closing
odds cannot be captured live -- the market settles and disappears at full time --
but football-data.co.uk archives both the opening and closing price for every
fixture, across several books plus the Betfair Exchange. Pulling that weekly gives
us the whole picture for nothing, and replaces what would otherwise have been two
extra scraping runs every day.

What it adds to each matched, graded log entry:
    odds_open   best available at open      (Max columns)
    odds_close  best available at close     (MaxC columns)
    b365_close  Bet365 close                (B365C) -- matches the backtest benchmark
    exch_close  Betfair Exchange close      (BFEC) -- sharpest available
    close_pct   de-vigged closing probabilities
    drift       close_pct minus the morning market, per outcome, in points

Usage:
    python3 enrich_closing.py log.json [out.json] [--local DIR] [--season 2627]

--local reads E0..E3.csv from DIR instead of the website (for testing).
Safe to run repeatedly: entries already carrying odds_close are left alone.
"""

import csv, io, json, os, sys, urllib.request

import teams as fe_teams

BASE = "https://www.football-data.co.uk/mmz4281"
DIVS = {"E0": "Premier League", "E1": "Championship",
        "E2": "League One", "E3": "League Two"}
OUTCOMES = ("H", "D", "A")


def fetch(season, div, local=None):
    if local:
        p = os.path.join(local, div + ".csv")
        if not os.path.exists(p):
            return None
        return open(p, encoding="utf-8", errors="replace").read()
    url = f"{BASE}/{season}/{div}.csv"
    try:
        with urllib.request.urlopen(url, timeout=45) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  WARN could not fetch {url}: {e}")
        return None


def num(v):
    try:
        f = float(v)
        return f if f > 1.0 else None
    except (TypeError, ValueError):
        return None


def devig(o):
    if not o or any(o.get(k) is None for k in OUTCOMES):
        return None
    inv = {k: 1.0 / o[k] for k in OUTCOMES}
    t = sum(inv.values())
    return {k: round(100 * inv[k] / t, 1) for k in OUTCOMES}


def iso_date(s):
    """football-data uses dd/mm/yy or dd/mm/yyyy."""
    p = str(s).strip().split("/")
    if len(p) != 3:
        return None
    d, m, y = p
    if len(y) == 2:
        y = "20" + y
    return f"{y}-{int(m):02d}-{int(d):02d}"


def load_rows(season, local=None):
    """Return {(date, home_canon, away_canon): row} across all four divisions."""
    out = {}
    for div in DIVS:
        text = fetch(season, div, local)
        if not text:
            continue
        n = 0
        for row in csv.DictReader(io.StringIO(text)):
            d = iso_date(row.get("Date"))
            h, a = row.get("HomeTeam"), row.get("AwayTeam")
            if not (d and h and a):
                continue
            out[(d, h.strip().lower(), a.strip().lower())] = row
            n += 1
        print(f"  {div}: {n} rows")
    return out


def canon(name, known):
    r, _ = fe_teams.resolve(name, known)
    return (r or str(name)).strip().lower()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    log_p = args[0]
    out_p = args[1] if len(args) > 1 else log_p
    local = None
    season = "2627"
    for i, a in enumerate(sys.argv):
        if a == "--local" and i + 1 < len(sys.argv):
            local = sys.argv[i + 1]
        if a == "--season" and i + 1 < len(sys.argv):
            season = sys.argv[i + 1]

    log = json.load(open(log_p))
    try:
        known = json.load(open("ratings.json"))["teams"]
    except Exception:
        known = []

    print(f"Loading football-data ({'local ' + local if local else 'season ' + season}):")
    rows = load_rows(season, local)
    if not rows:
        print("ENRICH: no source data available; log unchanged")
        json.dump(log, open(out_p, "w"), indent=1)
        return

    # index the source by canonical names so spelling differences don't block a match
    idx = {}
    for (d, h, a), row in rows.items():
        idx[(d, canon(h, known), canon(a, known))] = row

    matched = skipped = already = 0
    for m in log:
        if m.get("status") != "final":
            continue
        if m.get("odds_close"):
            already += 1
            continue
        key = (m.get("date"), canon(m.get("home"), known), canon(m.get("away"), known))
        row = idx.get(key)
        if not row:
            skipped += 1
            continue

        op = {k: num(row.get("Max" + k)) for k in OUTCOMES}
        cl = {k: num(row.get("MaxC" + k)) for k in OUTCOMES}
        b3 = {k: num(row.get("B365C" + k)) for k in OUTCOMES}
        ex = {k: num(row.get("BFEC" + k)) for k in OUTCOMES}
        close_pct = devig(cl) or devig(b3) or devig(ex)
        if not close_pct:
            skipped += 1
            continue

        m["odds_open"] = {k: v for k, v in op.items() if v}
        m["odds_close"] = {k: v for k, v in cl.items() if v}
        if all(b3.values()):
            m["b365_close"] = b3
        if all(ex.values()):
            m["exch_close"] = ex
        m["close_pct"] = close_pct
        if m.get("market_pct"):
            m["drift"] = {k: round(close_pct[k] - m["market_pct"][k], 1) for k in OUTCOMES}
        matched += 1

    json.dump(log, open(out_p, "w"), indent=1)
    print(f"ENRICH OK: {matched} fixtures enriched, {already} already had closing odds, "
          f"{skipped} not found in source -> {out_p}")


if __name__ == "__main__":
    main()
