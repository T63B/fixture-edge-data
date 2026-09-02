# Fixture Edge — Project State

**Read this first.** Scheduled runs are fresh sessions with no memory of the
conversation that built them. Anything not written down here is lost.

Last updated: 2026-09-02

## What this is

A daily forecast dashboard for the English Premier League, Championship, League
One and League Two. Live at:
https://claude.ai/code/artifact/a586275e-dba6-4d2c-9ae3-1df51e1bc6a7

## Architecture (current, v3)

Code and data live in this repo; the daily job clones it, researches fixtures and
odds, runs `generate.py`, publishes the artifact, and commits the log back.
Design and maths are in code, so the page cannot drift between runs.

See `RUNBOOK.md` for the run steps and `README.md` for the file map.

## Status as of 2026-09-02: working, with the log stored in the page

Confirmed working from scheduled runs: cloning this repo, running generate.py,
and publishing the dashboard. The 1 Sep 14:44 run and the 2 Sep 06:16 run both
produced correct pages.

Confirmed NOT working: every write to this repo. `git push` and the GitHub
contents API are both refused from the scheduled sandbox, while the identical
commands succeed from the user's Mac. This is a permission tier -- the sandbox's
repo attachment grants read access only. The original proxy error said so:
"if you need GitHub API or write access, call add_repo again with access:push".
Do not try to work around it from inside a run; it cannot be done.

**Therefore the log lives in the published page, not in this repo.** generate.py
embeds the full history in a `<script id="fixture-edge-log">` block. A run
recovers history by reading the previous page (Artifact `read`, then
`extract_log.py`) and persists it by publishing the new page. Both of those work
from the sandbox. `log.json` in this repo is a stale leftover -- ignore it.

This makes the publish the single point of failure for the whole tool: it carries
both the day's forecasts and all accumulated history.

**Still unverified at time of writing:** whether a scheduled run can successfully
perform the Artifact `read`. The allowed-domains entry for
`*.frame.claudeusercontent.com` is in place and reads work in principle, but no
run has yet attempted one (earlier prompts explicitly forbade it). If reads turn
out to fail, the history will silently reset each day -- the run is instructed to
say so loudly in its summary if that happens.

## Route map (which paths work from where)

| Operation | Scheduled sandbox | User's Mac (device shell) | Cowork chat session |
|---|---|---|---|
| Clone this repo | YES | YES | NO (proxy 403, wants add_repo) |
| Write to this repo | NO (read-only) | YES | NO |
| Publish artifact | YES | n/a | YES |
| Read artifact | Expected yes, unproven | n/a | Only in sessions started after the domain was allowed |
| Web research | YES | n/a | YES |

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
