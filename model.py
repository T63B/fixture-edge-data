"""
Fixture Edge — Dixon-Coles forecasting model.

Fits attack/defence ratings for every English league club on a single shared
scale across all four divisions, so that promoted and relegated clubs carry
their form across division boundaries.

Model:
    home goals ~ Poisson(exp(atk_home - def_away + home_adv))
    away goals ~ Poisson(exp(atk_away - def_home))
with the Dixon-Coles low-score dependency correction (tau) and exponential
time-decay weighting of historical matches.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import json, os, glob

DIVISIONS = {"E0": "Premier League", "E1": "Championship",
             "E2": "League One", "E3": "League Two"}
MAX_GOALS = 10


def load_matches(data_dir):
    """Read every season workbook and return one tidy frame of English league matches."""
    frames = []
    for path in sorted(glob.glob(os.path.join(data_dir, "all-euro-data-*.xlsx"))):
        xl = pd.ExcelFile(path)
        for sheet in DIVISIONS:
            if sheet not in xl.sheet_names:
                continue
            df = xl.parse(sheet)
            need = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}
            if not need.issubset(df.columns):
                continue
            keep = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]
            for odds in ("B365H", "B365D", "B365A"):
                if odds in df.columns:
                    keep.append(odds)
            sub = df[keep].copy()
            sub["Div"] = sheet
            sub["Season"] = os.path.basename(path)
            frames.append(sub)
    all_m = pd.concat(frames, ignore_index=True)
    all_m["Date"] = pd.to_datetime(all_m["Date"], errors="coerce")
    all_m = all_m.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    all_m["FTHG"] = all_m["FTHG"].astype(int)
    all_m["FTAG"] = all_m["FTAG"].astype(int)
    return all_m.sort_values("Date").reset_index(drop=True)


def dc_tau(hg, ag, lh, la, rho):
    """Dixon-Coles correction for the dependency between low scores."""
    t = np.ones_like(lh, dtype=float)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    t[m00] = 1 - lh[m00] * la[m00] * rho
    t[m01] = 1 + lh[m01] * rho
    t[m10] = 1 + la[m10] * rho
    t[m11] = 1 - rho
    return np.clip(t, 1e-10, None)


def fit(matches, half_life_days=365.0, ref_date=None):
    """Fit ratings by weighted maximum likelihood. Returns a params dict."""
    teams = sorted(set(matches["HomeTeam"]) | set(matches["AwayTeam"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    hi = matches["HomeTeam"].map(idx).to_numpy()
    ai = matches["AwayTeam"].map(idx).to_numpy()
    hg = matches["FTHG"].to_numpy()
    ag = matches["FTAG"].to_numpy()

    ref = pd.Timestamp(ref_date) if ref_date is not None else matches["Date"].max()
    age_days = (ref - matches["Date"]).dt.days.to_numpy().astype(float)
    weights = 0.5 ** (age_days / half_life_days)

    # params: [attack (n), defence (n), home_adv, rho]
    x0 = np.concatenate([np.zeros(n), np.zeros(n), [0.25], [-0.05]])

    def negll(p):
        atk = p[:n]
        dfn = p[n:2 * n]
        home_adv = p[2 * n]
        rho = p[2 * n + 1]
        lh = np.exp(atk[hi] - dfn[ai] + home_adv)
        la = np.exp(atk[ai] - dfn[hi])
        lh = np.clip(lh, 1e-8, 15)
        la = np.clip(la, 1e-8, 15)
        ll = (poisson.logpmf(hg, lh) + poisson.logpmf(ag, la)
              + np.log(dc_tau(hg, ag, lh, la, rho)))
        # identifiability: mean attack pinned to zero
        penalty = 1000.0 * (atk.mean() ** 2 + dfn.mean() ** 2)
        return -np.sum(weights * ll) + penalty

    res = minimize(negll, x0, method="L-BFGS-B",
                   bounds=[(-3, 3)] * (2 * n) + [(-0.5, 1.0), (-0.3, 0.3)],
                   options={"maxiter": 3000, "maxfun": 200000})

    p = res.x
    return {
        "teams": teams,
        "attack": {t: float(p[idx[t]]) for t in teams},
        "defence": {t: float(p[n + idx[t]]) for t in teams},
        "home_adv": float(p[2 * n]),
        "rho": float(p[2 * n + 1]),
        "n_matches": int(len(matches)),
        "ref_date": str(ref.date()),
        "converged": bool(res.success),
    }


def score_matrix(params, home, away):
    """Probability matrix over scorelines for one fixture."""
    atk, dfn = params["attack"], params["defence"]
    if home not in atk or away not in atk:
        return None
    lh = np.exp(atk[home] - dfn[away] + params["home_adv"])
    la = np.exp(atk[away] - dfn[home])
    lh, la = float(np.clip(lh, 1e-8, 15)), float(np.clip(la, 1e-8, 15))

    hs = poisson.pmf(np.arange(MAX_GOALS + 1), lh)
    as_ = poisson.pmf(np.arange(MAX_GOALS + 1), la)
    m = np.outer(hs, as_)

    rho = params["rho"]
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def predict(params, home, away):
    """Return {'H','D','A'} probabilities as percentages, or None if unknown teams."""
    m = score_matrix(params, home, away)
    if m is None:
        return None
    h = float(np.tril(m, -1).sum())
    d = float(np.trace(m))
    a = float(np.triu(m, 1).sum())
    tot = h + d + a
    return {"H": round(100 * h / tot, 1), "D": round(100 * d / tot, 1),
            "A": round(100 * a / tot, 1)}


def devig(oh, od, oa):
    """De-vig decimal odds into market-implied percentages."""
    try:
        ih, idr, ia = 1 / float(oh), 1 / float(od), 1 / float(oa)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    t = ih + idr + ia
    if not np.isfinite(t) or t <= 0:
        return None
    return {"H": round(100 * ih / t, 1), "D": round(100 * idr / t, 1),
            "A": round(100 * ia / t, 1)}


def brier(pct, actual):
    return sum(((pct[k] / 100.0) - (1.0 if k == actual else 0.0)) ** 2
               for k in ("H", "D", "A"))


def backtest(matches, half_life_days=365.0, min_train=2000, step=200):
    """
    Walk-forward evaluation: repeatedly fit on everything before a cutoff and
    score the next block of matches, so the model never sees its own test data.
    Compares against Bet365's de-vigged prices on the same matches.
    """
    rows = []
    i = min_train
    while i < len(matches):
        train = matches.iloc[:i]
        test = matches.iloc[i:i + step]
        params = fit(train, half_life_days=half_life_days,
                     ref_date=train["Date"].max())
        for _, m in test.iterrows():
            pred = predict(params, m["HomeTeam"], m["AwayTeam"])
            if pred is None:
                continue
            actual = m["FTR"]
            row = {"date": m["Date"], "div": m["Div"], "actual": actual,
                   "model_brier": brier(pred, actual),
                   "model_pick": max(pred, key=pred.get)}
            mk = devig(m.get("B365H"), m.get("B365D"), m.get("B365A"))
            if mk:
                row["market_brier"] = brier(mk, actual)
                row["market_pick"] = max(mk, key=mk.get)
            rows.append(row)
        i += step
    return pd.DataFrame(rows)
