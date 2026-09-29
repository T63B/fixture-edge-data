# Fixture Edge — Project State

**Read this first.** Scheduled runs are fresh sessions with no memory of the
conversation that built them. Anything not written down here is lost.

Last updated: 2026-09-19 (model-led rebuild)

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

### That single point of failure fired, on 26-28 Sep 2026

A run could not read the previous page. extract_log.py, as written at the time,
treated "no log block found" as "this must be the first run", wrote an empty
array and let the run continue. The run then published -- and because publishing
overwrites the page, and the page was the only copy, **133 graded fixtures from
29 Aug to 25 Sep were destroyed.** Nothing in the repo held a copy; the archive
here only covers 29-30 Aug.

The code fault was a convenience for day one that became a demolition charge by
day thirty. Fixed 29 Sep 2026:

* `extract_log.py` now exits 2 and writes no output file on any failure -- block
  missing, unparseable, or shorter than the count the page declares. The run
  stops before it can publish. `--allow-empty` opts back into the old behaviour
  and exists only for bootstrapping a genuinely new page.
* `generate.py` embeds `data-count` on the log block, so a truncated read is
  detectable rather than silent, and refuses to build a page with fewer entries
  than `log_floor.txt` records (written by extract_log.py) unless
  `--allow-log-shrink` is passed.

**The principle, for anyone changing this later:** losing a day of forecasts is
cheap and recoverable; overwriting the record is neither. Any failure in the
history path must stop the run, never degrade it. Do not reintroduce a silent
fallback to an empty log, however reasonable it looks in isolation.

### The second copy, added 29 Sep 2026

The guards narrow the failure; they do not add redundancy. So the log now also
lives in the artifact's own database, which publishing cannot touch, and that is
the primary store. The page keeps its embedded copy as an independent backup.
Either can rebuild the other.

* The published page declares `capabilities: {db: {}}`. A publish that omits
  `capabilities` carries the declaration forward; passing `{}` would remove it.
* Collection `log`, one document per calendar month, id `YYYY-MM`, body
  `{"month", "count", "fixtures": [...]}`. One document per fixture would be
  wrong -- the database caps at 5,000 documents and this stream grows forever.
  Monthly buckets are about a dozen documents a year, each well inside the
  256 KiB document limit.
* `db_sync.py merge|split|check` converts between that shape and `log.json`.
  It reuses `dedupe()` and `write_floor()` from extract_log.py, which is why
  extract_log.py's `main()` now sits behind an `if __name__` guard.
* Writes pin `if_version` to the version read at the start of the run, so a
  concurrent write is refused rather than silently overwriting.

Verified end to end against the live artifact on 29 Sep 2026: write, read with
`out_dir` (the listing reports each document's version), merge, split, pinned
write-back, and a stale pin correctly refused. A write at `as_level: "view"` is
also refused, so a view-only viewer could not damage the log if the artifact is
ever shared.

**Still unverified at time of writing:** whether a scheduled run can successfully
perform the Artifact `read`. The allowed-domains entry for
`*.frame.claudeusercontent.com` is in place and reads work in principle, but no
run has yet attempted one (earlier prompts explicitly forbade it). If reads turn
out to fail, the history will silently reset each day -- the run is instructed to
say so loudly in its summary if that happens.

## 2026-09-05: research starved by the network allowlist

The morning run produced a page, but could not fetch a single sports or odds
source. It fell back to search snippets, achieved odds coverage of only 13 of 34
fixtures, and omitted several League One and Two fixtures it could not corroborate
across two sources. It reported all of this honestly on the page, which is how it
was noticed.

**Cause:** the environment had Network access = Custom with an allowed-domains
list containing only the artifact domain and three GitHub entries. Under Custom,
everything else is unreachable. Verified from a chat session: oddschecker.com,
foxsports.com and sportsmole.co.uk all fail to connect outright.

This was also the cause of the "odds found for only 8 of 24 fixtures" problem on
1-2 Sep, which was at the time diagnosed as a research-quality issue without
asking why coverage was poor. The allowlist added to unblock GitHub was starving
the research the whole time.

**Fix:** Network access set to Full, and `GITHUB_PAT` removed from the
environment variables. The repo is PUBLIC and clones anonymously, so no token is
needed; keeping a write-capable credential in a sandbox that reads untrusted web
pages all day was the main argument against opening egress, and removing it
settles that. If egress is ever narrowed again, remember that every research
source must be listed or the forecasts quietly degrade to model-only.

## FIRST THING TO CHECK IF RESEARCH GOES BAD

If a run reports poor odds coverage, sites "down", or connection errors (as opposed
to HTTP errors), **check the cloud environment's Network access setting before
anything else.** This has caused two separate incidents and days of quietly
degraded forecasts.

Settings live in the environment editor: Network access offers None / Trusted /
Full / Custom. As of 2026-09-05 it is set to **Full**, which is the intended state
and needs no domain list. Under **Custom**, only listed domains are reachable and
everything else fails at the connection level -- which looks like the whole
internet being down, not like a configuration problem, which is why it went
unnoticed for days.

If it is ever set back to Custom, these domains are needed as a minimum:

    *.frame.claudeusercontent.com     (artifact reads -- the log lives in the page)
    github.com                        (code; no token needed, the repo is public)
    api.github.com
    codeload.github.com
    oddschecker.com / www.oddschecker.com
    oddspedia.com
    betfair.com                       (exchange -- sharpest prices when reachable)
    bet365.com / www.bet365.com       (matches the BACKTEST.md benchmark)
    ladbrokes.com
    paddypower.com
    williamhill.com
    skybet.com
    foxsports.com / www.foxsports.com
    sportsmole.co.uk / www.sportsmole.co.uk
    bbc.com / bbc.co.uk
    skysports.com
    sofascore.com
    forebet.com
    sportsgambler.com
    fixturedownload.com

Note that GITHUB_PAT was deliberately removed from the environment variables on
2026-09-05. Nothing needs it: the repo is public and clones anonymously, sandbox
writes to it are refused anyway, and removing the only credential is what makes
Full egress a sensible trade for a job that reads untrusted web pages daily.
Do not reintroduce it without a reason.

## 2026-09-19: the forecast is now the MODEL, not the market

The tool previously published the de-vigged market price as its forecast. That was
a correct fix for an earlier problem (edges flagged from model-vs-market noise) but
it overshot: it removed the tool's independent opinion entirely, and a forecast that
IS the market price cannot identify value against the market. On the user's
instruction the design is reversed.

**Now:** the headline forecast is the model. The market is shown beside it as a
benchmark. Where they differ by 10pp or more the card is flagged as a disagreement
-- explicitly NOT as a betting signal, because the evidence says the market is the
better forecaster.

**The model** is Dixon-Coles ratings on one cross-division scale, blending a
goals fit and a shots-on-target fit at weight 0.4/0.6. See MODEL.md for what was
tested, what was rejected (per-club home advantage: worse) and the numbers.

**Staleness is the dominant error source** -- bigger than any structural change
tested, by roughly 24x. fit_model.py must run weekly. Ratings had gone 118 days
without a refit before this rebuild, which is why the live gap to the market
(0.023) was double the backtest gap (0.012).

**The history was rescued, not reset.** `model_raw_pct` had recorded the model's
own prediction all along, so extract_log.py migrates old entries to score the model
honestly over the full history rather than discarding 90 graded fixtures.

**Live position as at the rebuild** (90 graded, 52 with odds): model Brier 0.587 /
53.8% hit, market 0.564 / 57.7%. On the 11 fixtures where they disagreed by 10pp+,
model 0.710 vs market 0.619 -- the market was better precisely where the model spoke
loudest. Small sample, but that is the number to watch.

## Closing odds and CLV (added 2026-09-06)

`enrich_closing.py` runs daily and pulls football-data.co.uk's current-season files
(https://www.football-data.co.uk/mmz4281/2627/E0.csv and E1-E3) to attach opening
and closing prices to graded fixtures. This replaced a plan to scrape prices twice
a day near kick-off: the archive gives the same information for free, from a
canonical source, including best-available (Max), Bet365 (matching the backtest
benchmark) and the Betfair Exchange.

Closing odds CANNOT be captured live -- the market settles at full time and the
prices vanish. The archive is the only route, and it lags by a few days, so CLV
arrives after the fact rather than same-day. That is fine for a track record.

Validated on 32 fixtures from last season: the closing price scored Brier 0.593
against the opening price's 0.604, with mean absolute drift of 2.11 points per
outcome. So forecasting at 07:00 costs roughly 0.011 Brier against forecasting at
kick-off -- small, real, and now measured on live data rather than assumed.

Note that CLV is only meaningful for flagged edges. Because the forecast IS the
de-vigged morning price, an unadjusted fixture has no view of its own to test; only
fixtures where researched team news moved the number off the market can be scored
this way.

## Route map (which paths work from where)

| Operation | Scheduled sandbox | User's Mac (device shell) | Cowork chat session |
|---|---|---|---|
| Clone this repo (no token needed; repo is public) | YES | YES | NO (proxy 403, wants add_repo) |
| Write to this repo | NO (read-only) | YES | NO |
| Publish artifact | YES | n/a | YES |
| Read artifact | Expected yes, unproven | n/a | Only in sessions started after the domain was allowed |
| Web research | ONLY if the domains are reachable under the network setting | n/a | YES |

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
