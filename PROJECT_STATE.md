# Fixture Edge — Project State

**Read this first.** Scheduled runs are fresh sessions with no memory of the
conversation that built them. Anything not written down here is lost.

Last updated: 2026-08-31

## What this is

A daily forecast dashboard for the English Premier League, Championship, League
One and League Two. Live at:
https://claude.ai/code/artifact/a586275e-dba6-4d2c-9ae3-1df51e1bc6a7

## Architecture (current, v3)

Code and data live in this repo; the daily job clones it, researches fixtures and
odds, runs `generate.py`, publishes the artifact, and commits the log back.
Design and maths are in code, so the page cannot drift between runs.

See `RUNBOOK.md` for the run steps and `README.md` for the file map.

## Infrastructure constraints (verified 2026-08-31)

| Capability | Status |
|---|---|
| Publish artifact | Works |
| **Read** artifact back | **Blocked** — network allowlist blocks `*.frame.claudeusercontent.com`. This is why state lives in this repo and not in the page. |
| GitHub from a Cowork chat session | **Blocked** by the Anthropic session proxy (403, wants `add_repo`, which Cowork sessions do not have). PATs do not help. |
| GitHub from the user's Mac (device shell) | **Works** — this is the only interactive path to the repo. |
| GitHub from the scheduled job's environment | Works (`$GITHUB_PAT`) |
| Local folder from scheduled runs | Not available — scheduled tasks are cloud-only |

## History — do not repeat these

- **v1**: log embedded in the published page. Failed: scheduled runs cannot read
  the artifact back. Trigger deleted.
- **v2**: log in this repo, but the page rebuilt each morning from a prose design
  spec in the trigger prompt. Fragile and drifted; a run reported SUCCEEDED in 52
  seconds having published nothing. Superseded by v3.
- During v2 debugging, a chain of one-shot "check whether it worked" triggers was
  created. Noise. Never do this — investigate within the run and report.
- A trigger reporting SUCCEEDED is **not** evidence the page updated. Verify the
  date on the page itself.

## The log and its methodology break

`log.json` was reset to empty on 2026-08-31. Predictions made on 29-30 August
used a superseded method whose "edges" came from model-versus-market noise;
mixing them into the track record would make the metrics meaningless. Track
record starts fresh from the first v3 run.

## Model status — read BACKTEST.md before touching this

The published forecast is the **de-vigged market price**. The Dixon-Coles model
is computed and displayed for comparison, and used as a fallback when a fixture
has no odds, but carries **zero weight** in the forecast. This is an evidence-based
decision: over 5,103 out-of-sample matches, every non-zero blend weight made
accuracy worse, monotonically. Do not raise `MODEL_WEIGHT` without beating
Brier 0.61262 on a fresh walk-forward run.

`ROADMAP.md` lists the agreed refinements (per-club home/away scoring splits,
weather as a variance effect, shot-based ratings, decay tuning). All deferred
until the pipeline is reliably running, and all subject to the same benchmark.

## Source data

Four seasons of football-data.co.uk results (2022-23 to 2025-26, 8,144 matches,
98 clubs) live in the user's local `Football Forecast/Historical Results` folder.
Not in this repo — they are the input to refitting `ratings.json`, which is done
occasionally from an interactive session, not in the daily run.
