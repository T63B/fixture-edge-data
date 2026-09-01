# Fixture Edge — Project State

**Read this first.** Scheduled runs are fresh sessions with no memory of the
conversation that built them. Anything not written down here is lost.

Last updated: 2026-09-01

## What this is

A daily forecast dashboard for the English Premier League, Championship, League
One and League Two. Live at:
https://claude.ai/code/artifact/a586275e-dba6-4d2c-9ae3-1df51e1bc6a7

## Architecture (current, v3)

Code and data live in this repo; the daily job clones it, researches fixtures and
odds, runs `generate.py`, publishes the artifact, and commits the log back.
Design and maths are in code, so the page cannot drift between runs.

See `RUNBOOK.md` for the run steps and `README.md` for the file map.

## Status as of 2026-09-01: pipeline WORKING, log persistence unconfirmed

The 14:44 run on 1 Sep cloned this repo, executed generate.py and published the
dashboard (page footer read "Generated 01 Sep 2026 14:55 UTC"). The v3 pipeline
works end to end for generate-and-publish.

**What fixed it:** the cloud environment had Network access = Custom with only
`*.frame.claudeusercontent.com` in the allowed-domains list, so github.com was
unreachable and every clone/push hung. Adding `github.com`, `api.github.com` and
`codeload.github.com` to that list resolved it. If runs ever start failing again,
check that list FIRST -- it was the cause of days of confusion.

**Still open:** no run has yet committed log.json back. Until that works the
Track Record cannot accumulate, because each run starts from an empty log. The
token in $GITHUB_PAT does have write permission (it has been used to push to this
repo from the user's Mac repeatedly). So the likely cause is the run not reaching
or not completing the push step, rather than a permissions problem. RUNBOOK step
1b (the early RUNLOG.md write-check) exists to make this visible; if RUNLOG.md
appears in this repo, writes work.

## Infrastructure constraints (verified 2026-09-01)

| Capability | Status |
|---|---|
| Publish artifact from a scheduled run | WORKS (proven 1 Sep) |
| Clone this repo from a scheduled run | WORKS (proven 1 Sep, after the allowlist fix) |
| Push to this repo from a scheduled run | UNCONFIRMED -- no commit has landed yet |
| Push to this repo from the user's Mac (device shell) | WORKS |
| Read artifact | Allowed domain now present; a session started before that change still cannot |
| GitHub from a Cowork *chat* session's own bash | BLOCKED by the Anthropic session proxy (wants `add_repo`, unavailable in Cowork). Use the device shell instead. |
| Local folder from scheduled runs | NOT AVAILABLE -- scheduled tasks are cloud-only |

## A note on diagnosing this system

Feedback is slow and indirect. A trigger's "SUCCEEDED" status only means the
session ended without crashing -- it is NOT the run's own verdict, and a run can
report SUCCEEDED having published nothing. Equally, absence of a commit a few
minutes in does not mean failure: on 1 Sep a run was wrongly written off as broken
when it published successfully sixty seconds after checking stopped. Wait for
evidence rather than inferring from its absence, and prefer side-effects you can
verify (a commit, a page timestamp) over status fields.

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
