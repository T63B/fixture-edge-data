#!/usr/bin/env python3
"""
Fixture Edge -- rebuild the lost 29 Aug to 25 Sep 2026 forecasts, week by week.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
On 26-28 Sep 2026 a run published an empty log over the page and destroyed 133
graded fixtures. This script reconstructs that period from archived results and
odds, so the dashboard has something to look at and the model has more fixtures
to be examined on.

IT IS NOT THE LOST RECORD, AND IT IS NOT A LIVE ONE. It is a backtest dressed in
the log's clothes, and it differs from what the tool actually published in four
ways, every one of which flatters the reconstruction:

 1. RATINGS. Through that period the live tool ran on ratings fitted to data
    ending 2026-05-24 -- up to 118 days stale, which nobody noticed at the time.
    This script refits before every week. Since staleness is the largest single
    error source in this model (the gap to the market roughly doubles between
    fresh and three months old), the reconstructed model will score better than
    the one that was really publishing. This is the big one.
 2. ADJUSTMENTS. The live forecasts included hand adjustments for injuries,
    suspensions and rotation risk, with stated reasons. None of that survives.
 3. ODDS. The live log recorded the best price findable at 07:00. This uses the
    archive's opening best price across the sampled books -- close in spirit,
    not the same number, and never the same bookmaker set.
 4. COVERAGE. The live log held only fixtures the tool actually found. This
    holds every fixture that was played, which silently erases the tool's own
    misses -- and it did miss, most clearly on 3 Oct when it skipped two whole
    divisions.

So these entries carry `"reconstructed": true` and are written to a SEPARATE
store from the live log. generate.py renders them in their own section with
their own numbers. They must never be averaged into the live Brier score or hit
rate: those answer "what did this tool predict before kickoff, and how did it
do", and a reconstruction cannot answer that question.

WALK-FORWARD DISCIPLINE
-----------------------
The one thing that would make this worthless is letting the model see the
results it is being asked to predict. So, for each week block, the model is
refitted on matches STRICTLY BEFORE that block's first day, with the time-decay
reference date set to the day before it. A fixture is never in its own training
set, and neither is any later fixture. The script asserts this per block and
refuses to write output if it is ever violated.

Usage:
    python3 reconstruct.py [--out reconstruction.json]
                           [--from 2026-08-29] [--to 2026-09-25]
                           [--history matches_history.csv] [--season 2627]
"""

import json
import os
import sys
import urllib.request
from io import StringIO

import numpy as np
import pandas as pd

import model2 as M

BLEND_W = 0.4
HALF_LIFE = 365.0
BASE = "https://www.football-data.co.uk/mmz4281"
DIVS = {"E0": "Premier League", "E1": "Championship",
        "E2": "League One", "E3": "League Two"}

# Odds preference, best-price-first to match what the live tool recorded.
# Max* is the maximum across the sampled books at opening; B365* is one book's
# opening price; Avg* is the mean. Closing prices (the *C* columns) are
# deliberately NOT preferred: the live tool priced at 07:00, not at kickoff.
ODDS_SETS = [
    ("max_opening", ("MaxH", "MaxD", "MaxA")),
    ("b365_opening", ("B365H", "B365D", "B365A")),
    ("avg_opening", ("AvgH", "AvgD", "AvgA")),
]


def fetch_season(season):
    frames = []
    for div in DIVS:
        url = f"{BASE}/{season}/{div}.csv"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                txt = r.read().decode("utf-8", "replace")
            df = pd.read_csv(StringIO(txt))
        except Exception as e:
            print(f"  WARN {div}: {e}")
            continue
        if "FTHG" not in df.columns:
            continue
        df = df.dropna(subset=["FTHG", "FTAG", "HomeTeam", "AwayTeam"])
        df["Div"] = div
        for c in ("HST", "AST"):
            if c not in df.columns:
                df[c] = np.nan
        for _, cols in ODDS_SETS:
            for c in cols:
                if c not in df.columns:
                    df[c] = np.nan
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        frames.append(df)
        print(f"  {div}: {len(df)} played")
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def pick_odds(row):
    """Best available opening price triple, with its provenance."""
    for name, cols in ODDS_SETS:
        vals = [row.get(c) for c in cols]
        if all(v is not None and pd.notna(v) and float(v) > 1.0 for v in vals):
            dec = {k: float(v) for k, v in zip(("H", "D", "A"), vals)}
            book = M.devig(dec["H"], dec["D"], dec["A"])
            if book is None:
                continue
            overround = sum(1.0 / dec[k] for k in ("H", "D", "A")) * 100.0
            if not (98.0 <= overround <= 125.0):
                continue  # the same sanity check the live run applies
            return name, dec, book, overround
    return None, None, None, None


def main():
    out = "reconstruction.json"
    hist = "matches_history.csv"
    season = "2627"
    d_from, d_to = "2026-08-29", "2026-09-25"
    for i, a in enumerate(sys.argv):
        nxt = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if a == "--out" and nxt: out = nxt
        if a == "--history" and nxt: hist = nxt
        if a == "--season" and nxt: season = nxt
        if a == "--from" and nxt: d_from = nxt
        if a == "--to" and nxt: d_to = nxt

    lo, hi = pd.Timestamp(d_from), pd.Timestamp(d_to)

    if not os.path.exists(hist):
        sys.exit(f"RECON FAILED: history file {hist} not found")
    h = pd.read_csv(hist)
    h["Date"] = pd.to_datetime(h["Date"], errors="coerce")
    h = h.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    print(f"history: {len(h)} matches to {h['Date'].max().date()}")

    print(f"current season ({season}):")
    cur = fetch_season(season)
    if cur is None or not len(cur):
        sys.exit("RECON FAILED: no current-season data. The reconstruction needs "
                 "results and odds for the target window; without them there is "
                 "nothing to rebuild from. Check network access and retry.")

    # Training pool: history plus every current-season result.
    pool_cols = ["Date", "Div", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HST", "AST"]
    pool = pd.concat([h.reindex(columns=pool_cols),
                      cur.reindex(columns=pool_cols)], ignore_index=True)
    pool = pool.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    pool = pool.drop_duplicates(subset=["Date", "HomeTeam", "AwayTeam"], keep="last")
    pool["FTHG"] = pool["FTHG"].astype(int)
    pool["FTAG"] = pool["FTAG"].astype(int)
    pool = pool.sort_values("Date").reset_index(drop=True)

    # Target fixtures: played, in window, in the four English divisions.
    tgt = cur[(cur["Date"] >= lo) & (cur["Date"] <= hi) & cur["Div"].isin(DIVS)].copy()
    tgt = tgt.sort_values("Date").reset_index(drop=True)
    if not len(tgt):
        sys.exit(f"RECON FAILED: no fixtures found between {d_from} and {d_to}.")
    print(f"target window: {len(tgt)} fixtures, "
          f"{tgt['Date'].min().date()} to {tgt['Date'].max().date()}")

    # Week blocks, Monday-anchored, so each refit is "as of" a Monday morning.
    tgt["block"] = tgt["Date"].dt.to_period("W-SUN").apply(lambda p: p.start_time)

    entries, skipped, blocks = [], [], []
    for block_start, grp in tgt.groupby("block", sort=True):
        train = pool[pool["Date"] < block_start]
        # The guarantee this whole exercise rests on.
        assert train["Date"].max() < block_start, "training data leaks into the block"
        assert train["Date"].max() < grp["Date"].min(), "training data leaks past the block"
        ref = block_start - pd.Timedelta(days=1)
        print(f"\nblock {block_start.date()} ({len(grp)} fixtures): "
              f"fitting on {len(train)} matches to {train['Date'].max().date()}")
        g = M.fit(train, "goals", half_life=HALF_LIFE, ref_date=ref)
        s = M.fit(train, "sot", half_life=HALF_LIFE, ref_date=ref)
        if g is None:
            sys.exit("RECON FAILED: goals model did not fit for a block")
        blocks.append({"block_start": str(block_start.date()),
                       "fitted_to": str(train["Date"].max().date()),
                       "train_matches": int(len(train)),
                       "fixtures": int(len(grp)),
                       "converged": bool(g["converged"])})

        for _, r in grp.iterrows():
            mp = M.predict(g, r["HomeTeam"], r["AwayTeam"],
                           blend_with=s, weight=BLEND_W)
            if mp is None:
                skipped.append({"date": str(r["Date"].date()),
                                "home": r["HomeTeam"], "away": r["AwayTeam"],
                                "why": "no rating for one or both clubs"})
                continue
            basis, dec, book, overround = pick_odds(r)
            res = ("H" if r["FTHG"] > r["FTAG"]
                   else "A" if r["FTAG"] > r["FTHG"] else "D")
            e = {
                "id": f"{r['Date'].date()}|{DIVS[r['Div']]}|{r['HomeTeam']}|{r['AwayTeam']}",
                "date": str(r["Date"].date()),
                "league": DIVS[r["Div"]],
                "home": r["HomeTeam"], "away": r["AwayTeam"],
                "model_pct": {k: round(mp[k], 1) for k in ("H", "D", "A")},
                "status": "final",
                "result": res,
                "score": f"{int(r['FTHG'])}-{int(r['FTAG'])}",
                "reconstructed": True,
                "fitted_to": str(train["Date"].max().date()),
                "block_start": str(block_start.date()),
            }
            if book:
                e["market_pct"] = {k: round(book[k], 1) for k in ("H", "D", "A")}
                e["odds_dec"] = dec
                e["odds_basis"] = basis
                e["overround"] = round(overround, 1)
            entries.append(e)

    entries.sort(key=lambda m: (m["date"], m["league"], m["home"]))
    priced = sum(1 for m in entries if m.get("market_pct"))
    bundle = {
        "reconstructed": True,
        "window": {"from": d_from, "to": d_to},
        "built_at": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "method": ("week-by-week walk-forward: for each Monday-anchored block the "
                   "model is refitted on matches strictly before that block, with "
                   "the time-decay reference set to the preceding day"),
        "blend_weight": BLEND_W,
        "half_life": HALF_LIFE,
        "caveats": [
            "NOT the lost record and NOT a live one -- a backtest in the log's shape.",
            "The live tool ran on ratings up to 118 days stale; this refits weekly, "
            "so the reconstructed model scores better than the tool really did.",
            "Hand adjustments for injuries, suspensions and rotation are unrecoverable.",
            "Odds are the archive's opening best price, not the best price findable "
            "at 07:00 from the books the live run used.",
            "Every fixture played is included, so the tool's own missed fixtures "
            "are silently erased.",
            "Must never be averaged into the live Brier score or hit rate.",
        ],
        "blocks": blocks,
        "count": len(entries),
        "priced": priced,
        "skipped": skipped,
        "fixtures": entries,
    }
    json.dump(bundle, open(out, "w"), indent=1)

    # Headline numbers, for the run's own sanity check only.
    def avg(f, rows):
        v = [f(m) for m in rows]
        v = [x for x in v if x is not None]
        return sum(v) / len(v) if v else None
    both = [m for m in entries if m.get("market_pct")]
    mb = avg(lambda m: M.brier(m["model_pct"], m["result"]), both)
    kb = avg(lambda m: M.brier(m["market_pct"], m["result"]), both)
    print(f"\nRECON OK: {len(entries)} fixtures ({priced} priced, "
          f"{len(skipped)} skipped) over {len(blocks)} week blocks -> {out}")
    if mb is not None:
        print(f"  on the {len(both)} priced fixtures: model Brier {mb:.4f}, "
              f"market {kb:.4f}")
    print("  REMINDER: reconstructed, not a live record. Keep it out of the live metrics.")


if __name__ == "__main__":
    main()
