"""
Fixture Edge — model variants for evaluation.

The published model must be chosen on evidence, not preference: every variant here
is scored by walk-forward backtest against the incumbent (goals-only Dixon-Coles,
365-day half-life, single global home advantage, Brier 0.6255 out-of-sample).

Variants:
  goals     incumbent: Poisson/Dixon-Coles on goals
  sot       ratings fitted to shots on target, converted to goals via league rate
  blend     geometric blend of the two lambdas (shots stabilise faster than goals)
  ha        per-club home advantage, shrunk toward the league mean
"""

import glob
import os

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

DIVISIONS = {"E0": "Premier League", "E1": "Championship",
             "E2": "League One", "E3": "League Two"}
MAX_GOALS = 10


def load(data_dir):
    """Tidy frame of English league matches, with shots where available."""
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
            keep = list(need)
            for c in ("HST", "AST", "HS", "AS", "B365H", "B365D", "B365A",
                      "MaxH", "MaxD", "MaxA"):
                if c in df.columns:
                    keep.append(c)
            sub = df[keep].copy()
            sub["Div"] = sheet
            frames.append(sub)
    m = pd.concat(frames, ignore_index=True)
    m["Date"] = pd.to_datetime(m["Date"], errors="coerce")
    m = m.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    m["FTHG"] = m["FTHG"].astype(int)
    m["FTAG"] = m["FTAG"].astype(int)
    return m.sort_values("Date").reset_index(drop=True)


def dc_tau(hg, ag, lh, la, rho):
    t = np.ones_like(lh, dtype=float)
    for mask, val in (((hg == 0) & (ag == 0), None), ((hg == 0) & (ag == 1), None),
                      ((hg == 1) & (ag == 0), None), ((hg == 1) & (ag == 1), None)):
        pass
    m00 = (hg == 0) & (ag == 0); m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0); m11 = (hg == 1) & (ag == 1)
    t[m00] = 1 - lh[m00] * la[m00] * rho
    t[m01] = 1 + lh[m01] * rho
    t[m10] = 1 + la[m10] * rho
    t[m11] = 1 - rho
    return np.clip(t, 1e-10, None)


def fit(matches, response="goals", half_life=365.0, per_club_ha=False,
        ha_shrink=25.0, ref_date=None):
    """
    response: 'goals' (FTHG/FTAG) or 'sot' (HST/AST)
    per_club_ha: give each club its own home advantage, shrunk toward the mean
    ha_shrink: pseudo-matches of shrinkage on the per-club term (higher = tighter)
    """
    if response == "sot":
        if "HST" not in matches.columns:
            return None
        m = matches.dropna(subset=["HST", "AST"]).copy()
        yh = m["HST"].astype(int).to_numpy()
        ya = m["AST"].astype(int).to_numpy()
        use_tau = False
    else:
        m = matches
        yh = m["FTHG"].to_numpy()
        ya = m["FTAG"].to_numpy()
        use_tau = True

    teams = sorted(set(m["HomeTeam"]) | set(m["AwayTeam"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = m["HomeTeam"].map(idx).to_numpy()
    ai = m["AwayTeam"].map(idx).to_numpy()

    ref = pd.Timestamp(ref_date) if ref_date is not None else m["Date"].max()
    age = (ref - m["Date"]).dt.days.to_numpy().astype(float)
    w = 0.5 ** (age / half_life)

    nha = n if per_club_ha else 0
    x0 = np.concatenate([np.zeros(n), np.zeros(n), [0.25], [-0.05], np.zeros(nha)])

    # count home matches per club for shrinkage weighting
    home_counts = np.bincount(hi, weights=w, minlength=n) if per_club_ha else None

    def negll(p):
        atk = p[:n]; dfn = p[n:2 * n]
        ha = p[2 * n]; rho = p[2 * n + 1]
        extra = p[2 * n + 2:] if per_club_ha else None
        club_ha = ha + (extra[hi] if per_club_ha else 0.0)
        lh = np.clip(np.exp(atk[hi] - dfn[ai] + club_ha), 1e-8, 25)
        la = np.clip(np.exp(atk[ai] - dfn[hi]), 1e-8, 25)
        ll = poisson.logpmf(yh, lh) + poisson.logpmf(ya, la)
        if use_tau:
            ll = ll + np.log(dc_tau(yh, ya, lh, la, rho))
        pen = 1000.0 * (atk.mean() ** 2 + dfn.mean() ** 2)
        if per_club_ha:
            # shrink each club's home term toward zero in proportion to how little
            # home data supports it -- stops League Two clubs inventing huge effects
            pen = pen + np.sum(extra ** 2 * (ha_shrink / (home_counts + 1.0)) * 50.0)
        return -np.sum(w * ll) + pen

    bounds = [(-3, 3)] * (2 * n) + [(-0.5, 1.0), (-0.3, 0.3)] + [(-0.6, 0.6)] * nha
    res = minimize(negll, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 4000, "maxfun": 400000})
    p = res.x
    out = {
        "teams": teams, "response": response,
        "attack": {t: float(p[idx[t]]) for t in teams},
        "defence": {t: float(p[n + idx[t]]) for t in teams},
        "home_adv": float(p[2 * n]), "rho": float(p[2 * n + 1]),
        "per_club_ha": bool(per_club_ha),
        "club_ha": ({t: float(p[2 * n + 2 + idx[t]]) for t in teams} if per_club_ha else {}),
        "half_life": half_life, "n_matches": int(len(m)),
        "ref_date": str(ref.date()), "converged": bool(res.success),
    }
    if response == "sot":
        # conversion: goals per shot on target, from the same training window
        gh = matches["FTHG"].sum(); ga = matches["FTAG"].sum()
        sh = matches["HST"].sum(); sa = matches["AST"].sum()
        out["goals_per_sot"] = float((gh + ga) / max(sh + sa, 1))
    return out


def lambdas(params, home, away):
    atk, dfn = params["attack"], params["defence"]
    if home not in atk or away not in atk:
        return None
    ha = params["home_adv"]
    if params.get("per_club_ha"):
        ha = ha + params["club_ha"].get(home, 0.0)
    lh = float(np.clip(np.exp(atk[home] - dfn[away] + ha), 1e-8, 25))
    la = float(np.clip(np.exp(atk[away] - dfn[home]), 1e-8, 25))
    if params["response"] == "sot":
        c = params.get("goals_per_sot", 0.32)
        lh, la = lh * c, la * c
    return lh, la


def predict(params, home, away, rho=None, blend_with=None, weight=0.5):
    """1X2 percentages. blend_with: a second params dict to combine lambdas with."""
    lam = lambdas(params, home, away)
    if lam is None:
        return None
    lh, la = lam
    if blend_with is not None:
        lam2 = lambdas(blend_with, home, away)
        if lam2 is not None:
            lh = lh ** weight * lam2[0] ** (1 - weight)
            la = la ** weight * lam2[1] ** (1 - weight)
    r = params["rho"] if rho is None else rho
    hs = poisson.pmf(np.arange(MAX_GOALS + 1), lh)
    as_ = poisson.pmf(np.arange(MAX_GOALS + 1), la)
    mx = np.outer(hs, as_)
    mx[0, 0] *= 1 - lh * la * r
    mx[0, 1] *= 1 + lh * r
    mx[1, 0] *= 1 + la * r
    mx[1, 1] *= 1 - r
    mx = np.clip(mx, 0, None)
    mx /= mx.sum()
    h = float(np.tril(mx, -1).sum()); d = float(np.trace(mx)); a = float(np.triu(mx, 1).sum())
    t = h + d + a
    return {"H": 100 * h / t, "D": 100 * d / t, "A": 100 * a / t}


def brier(pct, actual):
    return sum(((pct[k] / 100.0) - (1.0 if k == actual else 0.0)) ** 2
               for k in ("H", "D", "A"))


def devig(oh, od, oa):
    try:
        i = [1 / float(oh), 1 / float(od), 1 / float(oa)]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    t = sum(i)
    if not np.isfinite(t) or t <= 0:
        return None
    return {"H": 100 * i[0] / t, "D": 100 * i[1] / t, "A": 100 * i[2] / t}
