# fixture-edge-data

Data and code behind **Fixture Edge**, a daily forecast dashboard for the English
Premier League, Championship, League One and League Two.

Live dashboard: https://claude.ai/code/artifact/a586275e-dba6-4d2c-9ae3-1df51e1bc6a7

This repo exists because the scheduled job that updates the dashboard runs in a
fresh session every morning with no memory of previous runs, and cannot read the
published page back. Everything the job needs to be consistent day to day lives
here.

## Files

| File | Purpose |
|---|---|
| `PROJECT_STATE.md` | **Read first.** Architecture, constraints, history of what has been tried. |
| `BACKTEST.md` | Why the model carries zero weight. Evidence, not opinion. |
| `RUNBOOK.md` | Step-by-step for the daily scheduled run. |
| `generate.py` | Builds `dashboard.html` deterministically. All maths and rendering. |
| `model.py` | Dixon-Coles fit / predict / de-vig helpers. |
| `teams.py` | Maps everyday club names onto the names used in the ratings. |
| `ratings.json` | Fitted attack/defence ratings, refreshed periodically. |
| `log.json` | Every prediction ever published, with results once known. |

## The daily flow

1. Fetch `log.json`, `ratings.json` and the `.py` files from this repo.
2. Research the day's fixtures, kickoff times and best available 1X2 odds.
   Grade any previously pending fixtures by looking up final scores.
3. Write `today.json` (schema documented at the top of `generate.py`).
4. `python3 generate.py today.json log.json ratings.json out.html new_log.json`
5. Publish `out.html` to the artifact URL above.
6. Commit `new_log.json` back here as `log.json`.

The agent's job is steps 2 and 3 — research and judgment. Steps 4 onward are
deterministic code, so the dashboard cannot drift in design or methodology from
one morning to the next.

## What this tool claims

That it presents the best publicly available probability for each fixture, with
the bookmaker's margin stripped out, in one place, across four divisions — and
that it keeps an honest scoreboard of its own accuracy.

## What it does not claim

That it beats the bookmakers. It does not. See `BACKTEST.md`.
