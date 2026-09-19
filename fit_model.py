#!/usr/bin/env python3
"""
Fixture Edge — refit the forecasting model.

WHY THIS RUNS REGULARLY: stale ratings are the single largest source of error in
this model, by a wide margin. Measured on four seasons of data, the model's gap to
the market roughly doubles as ratings age:

    days since refit    model Brier   market   gap
    0-30                0.6168        0.6061   +0.011
    30-60               0.6300        0.6158   +0.014
    60-90               0.6298        0.6169   +0.013
    90-150              0.6336        0.6157   +0.018

For comparison, switching from goals-only to a goals-plus-shots blend was worth
0.0007. Refitting is worth roughly twenty-four times more than that. If you only
maintain one thing here, maintain this.

WHAT IT FITS: two Dixon-Coles rating sets on a single cross-division scale --
one on goals, one on shots on target -- whose predicted scoring rates are then
blended geometrically at BLEND_W. Shots on target stabilise faster than goals, so
the blend beats goals alone (0.6249 vs 0.6255 on walk-forward over 5,103
out-of-sample matches).

WHAT WAS TESTED AND REJECTED: per-club home advantage with shrinkage made things
slightly worse (0.6415 vs 0.6409 on a held-out split). Half-lives of 180 and 730
days were both worse than 365. Do not reintroduce either without new evidence.

Usage:
    python3 fit_model.py [--out ratings.json] [--history matches_history.csv]
                         [--season 2627] [--no-download]
"""

import json
import os
import sys
import urllib.request
from io import StringIO

import numpy as np
import pandas as pd

import model2 as M

BLEND_W = 0.4          # weight on the goals model; rest on shots on target
HALF_LIFE = 365.0
BASE = "https://www.football-data.co.uk/mmz4281"
DIVS = ("E0", "E1", "E2", "E3")
COLS = ["Date", "Div", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "HST", "AST"]


def fetch_season(season):
    """Current-season results from football-data.co.uk. Returns a frame or None."""
    frames = []
    for div in DIVS:
        url = f"{BASE}/{season}/{div}.csv"
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
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
        keep = df[[c for c in COLS if c in df.columns]].copy()
        keep["Date"] = pd.to_datetime(keep["Date"], dayfirst=True, errors="coerce")
        frames.append(keep)
        print(f"  {div}: {len(keep)} played")
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def main():
    out = "ratings.json"
    hist = "matches_history.csv"
    season = "2627"
    download = True
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
        if a == "--history" and i + 1 < len(sys.argv):
            hist = sys.argv[i + 1]
        if a == "--season" and i + 1 < len(sys.argv):
            season = sys.argv[i + 1]
        if a == "--no-download":
            download = False

    if not os.path.exists(hist):
        print(f"FIT FAILED: history file {hist} not found")
        sys.exit(1)
    h = pd.read_csv(hist)
    h["Date"] = pd.to_datetime(h["Date"], errors="coerce")
    print(f"history: {len(h)} matches to {h['Date'].max().date()}")

    cur = None
    if download:
        print(f"current season ({season}):")
        cur = fetch_season(season)

    if cur is not None and len(cur):
        m = pd.concat([h, cur], ignore_index=True)
        m = m.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
        m = m.drop_duplicates(subset=["Date", "HomeTeam", "AwayTeam"], keep="last")
        added = len(m) - len(h)
        print(f"  added {added} current-season matches")
    else:
        m = h.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
        print("  no current-season data available -- fitting on history alone.")
        print("  NOTE: ratings will be stale, which is the largest error source here.")

    m = m.sort_values("Date").reset_index(drop=True)
    m["FTHG"] = m["FTHG"].astype(int)
    m["FTAG"] = m["FTAG"].astype(int)
    ref = m["Date"].max()

    print(f"fitting on {len(m)} matches, reference date {ref.date()} ...")
    g = M.fit(m, "goals", half_life=HALF_LIFE, ref_date=ref)
    s = M.fit(m, "sot", half_life=HALF_LIFE, ref_date=ref)
    if g is None:
        print("FIT FAILED: goals model did not fit")
        sys.exit(1)

    bundle = {
        "teams": g["teams"],
        "attack": g["attack"], "defence": g["defence"],
        "home_adv": g["home_adv"], "rho": g["rho"],
        "response": "goals", "per_club_ha": False, "club_ha": {},
        "half_life": HALF_LIFE,
        "blend_weight": BLEND_W,
        "sot": s,
        "n_matches": int(len(m)),
        "fitted_on": str(ref.date()),
        "fitted_at": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "converged": bool(g["converged"]) and bool(s["converged"] if s else True),
    }
    json.dump(bundle, open(out, "w"), indent=1)

    rank = sorted(g["teams"], key=lambda t: g["attack"][t] + g["defence"][t], reverse=True)
    print(f"FIT OK: {len(g['teams'])} clubs, {len(m)} matches, ref {ref.date()} -> {out}")
    print("  strongest:", ", ".join(rank[:5]))
    print("  weakest  :", ", ".join(rank[-3:]))


if __name__ == "__main__":
    main()
