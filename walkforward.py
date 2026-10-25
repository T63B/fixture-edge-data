#!/usr/bin/env python3
"""
Walk-forward harness: emit out-of-sample model probabilities for every match.

WHY: the live record keeps showing the same thing -- the model picks the right
outcome more often than the market (54.5% against 48.7%) while scoring worse on
Brier. That is a calibration defect, not a ranking one, and it is fixable in
principle. But 154 live fixtures cannot test a fix: an in-sample sweep on a
sample that size finds something flattering every time, which is exactly how the
shrinkage idea fooled me on 17 Oct.

So the fix has to be tested here, on four seasons, where there is power.

DISCIPLINE: for each monthly block the model is refitted on matches STRICTLY
before that block. No match is ever in its own training set. Output is one JSON
line per match: its probability, the result, the division, and the date, so the
recalibration work downstream can split by time and never fit and test on the
same period.

Usage: python3 walkforward.py <repo_dir> <out.jsonl> [--start 2023-08-01]
Resumable: blocks already present in the output file are skipped.
"""
import json, os, sys, time

import pandas as pd

BLEND_W = 0.4
HALF_LIFE = 365.0


def main():
    repo, out_p = sys.argv[1], sys.argv[2]
    start = "2023-08-01"
    for i, a in enumerate(sys.argv):
        if a == "--start" and i + 1 < len(sys.argv):
            start = sys.argv[i + 1]
    sys.path.insert(0, repo)
    import model2 as M

    h = pd.read_csv(os.path.join(repo, "matches_history.csv"))
    h["Date"] = pd.to_datetime(h["Date"], errors="coerce")
    h = h.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    h["FTHG"] = h["FTHG"].astype(int); h["FTAG"] = h["FTAG"].astype(int)
    h = h.sort_values("Date").reset_index(drop=True)

    done = set()
    if os.path.exists(out_p):
        for line in open(out_p):
            try:
                done.add(json.loads(line)["block"])
            except Exception:
                pass
        print("resuming: %d blocks already done" % len(done), flush=True)

    tgt = h[h["Date"] >= pd.Timestamp(start)].copy()
    tgt["block"] = tgt["Date"].dt.to_period("M").astype(str)
    blocks = [b for b in sorted(tgt["block"].unique()) if b not in done]
    print("%d blocks to do (%d matches total)" % (len(blocks), len(tgt)), flush=True)

    f = open(out_p, "a")
    for bi, b in enumerate(blocks):
        grp = tgt[tgt["block"] == b]
        lo = grp["Date"].min()
        train = h[h["Date"] < lo]
        assert train["Date"].max() < lo, "training data leaks into the block"
        t0 = time.time()
        g = M.fit(train, "goals", half_life=HALF_LIFE, ref_date=lo - pd.Timedelta(days=1))
        s = M.fit(train, "sot", half_life=HALF_LIFE, ref_date=lo - pd.Timedelta(days=1))
        if g is None:
            print("  %s: goals fit failed, skipped" % b, flush=True)
            continue
        wrote = 0
        for _, r in grp.iterrows():
            p = M.predict(g, r["HomeTeam"], r["AwayTeam"], blend_with=s, weight=BLEND_W)
            if p is None:
                continue
            res = "H" if r["FTHG"] > r["FTAG"] else ("A" if r["FTAG"] > r["FTHG"] else "D")
            f.write(json.dumps({
                "block": b, "date": str(r["Date"].date()), "div": r["Div"],
                "home": r["HomeTeam"], "away": r["AwayTeam"],
                "p": {k: round(p[k], 4) for k in ("H", "D", "A")},
                "result": res, "train_n": int(len(train)),
            }) + "\n")
            wrote += 1
        f.flush()
        print("  [%d/%d] %s  train %d  wrote %d  (%.0fs)"
              % (bi + 1, len(blocks), b, len(train), wrote, time.time() - t0), flush=True)
    f.close()
    print("WALKFORWARD DONE", flush=True)


main()
