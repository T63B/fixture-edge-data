# Daily run — runbook

The scheduled job runs at 06:00 UTC. It is a fresh session with no memory. Follow
these steps exactly; everything needed is in this repo.

Auth: the GitHub token is in `$GITHUB_PAT`. Repo is `T63B/fixture-edge-data`.

## 1. Pull the repo

```bash
cd /tmp && rm -rf fe && timeout 60 git clone -q https://github.com/T63B/fixture-edge-data.git fe && cd fe
```

No credential is needed: this repo is public and clones anonymously. Do not rely
on `$GITHUB_PAT` -- it may not be set, and it grants nothing the sandbox can use
(writes are refused regardless).

If git is blocked, fall back to the contents API per file (`GET /repos/T63B/fixture-edge-data/contents/<file>`,
base64-decode the `content` field, and keep the `sha` for writing back).

## 1a. Leave breadcrumbs, so a silent failure can be diagnosed

Do this immediately after the clone, and update it as you go. The scheduler
reports a run as SUCCEEDED whenever the session ends without throwing, which is
NOT the same as the job being done: on 1 Oct 2026 two runs reported success,
took 45 and 81 seconds, and published nothing at all. Nothing in the run was
recoverable afterwards, because a finished session leaves no trace this project
can read. So the run records its own progress in the database, which outlives it.

At the start, `ArtifactData` `set` on collection `status`, doc_id `last_run`:

    {"started": "<ISO timestamp>", "stage": "started", "trigger": "scheduled",
     "notes": []}

Then after each step below, `update` the same document with the stage reached,
pinning `if_version` to the version the last write returned:

    cloned -> log_recovered -> graded -> refitted -> enriched -> researched
    -> generated -> db_written -> published

Add a short line to `notes` whenever something is surprising — a blocked source,
an empty fixture list, a refit that failed. On the final update include
`"finished"`, the artifact version the publish returned, `"fixtures"`,
`"log_entries"`, and `"ok": true`.

If a later inspection finds `stage` short of `published`, that names the step
that failed. This costs a handful of tool calls and is the only way anyone finds
out where a dead run died. Do not skip it, and do not batch all the updates to
the end — a breadcrumb written after the fact is worthless.

## 1b. Recover the log (database first, page as backup)

**The repo is READ-ONLY from the scheduled sandbox.** Clone works; every write is
refused, `git push` and the GitHub contents API alike. This is a permission tier
on the sandbox's repo attachment, not a token or network problem, and it cannot
be worked around from inside a run. Do not spend time trying.

So the log does not live in the repo. It lives in the published page. `generate.py`
embeds the entire log in a `<script id="fixture-edge-log">` block, so yesterday's
page holds the full history, and publishing today's page is what persists it.

### The database is the primary copy; the page is the backup

Since 29 Sep 2026 the log ALSO lives in the artifact's own database, which
publishing cannot touch. That is the primary store. The copy embedded in the
page is kept as a second, independent copy, so either can rebuild the other.

Recover from the database like this:

1. `ArtifactData` `list`, collection `log`, `out_dir` `dbdocs`, on the dashboard
   URL in README.md. It saves one JSON file per month under `dbdocs/log/` and
   the result lists each document's **version** — write those down, they are
   needed to write back.
2. `python3 db_sync.py merge dbdocs log.json`

Expect `DB MERGE OK`. If it says the database holds no log documents and this is
not the first run after the migration, STOP: something is wrong, and writing an
empty log back would defeat the whole point of having two copies.

Recover from the page only if the database read fails:

1. Use the Artifact tool's `read` action on the dashboard URL in README.md and save
   the returned HTML to `prev.html`.
2. `python3 extract_log.py prev.html log.json`

You should see a line beginning `EXTRACT OK`. If BOTH stores fail to read, end the
run and publish nothing.

**If it prints `EXTRACT FAILED` and exits 2, the run stops there. Do not publish.**
This is not a speed bump to route around, and there is no fallback that preserves
the record -- publishing overwrites the page, and the page is the only copy of the
log, so a page built without the history erases it permanently. That is not a
hypothetical: between 26 and 28 Sep 2026 a run could not read the previous page,
started from an empty log, published it, and destroyed 133 graded fixtures. Losing
one day of forecasts costs a day. Publishing over the log costs everything.

So when extract fails: retry the artifact read (a truncated or partial read is the
usual cause), check the URL in README.md is right, and check the network. If it
still fails, end the run, publish nothing, and report exactly what the read did.
`--allow-empty` exists only for deliberately starting a brand-new page from
nothing, and must never be used to get an ordinary run unstuck.

extract_log.py also writes `log_floor.txt` — the number of entries it recovered.
generate.py refuses to build a page with fewer than that, so even if something
clobbers `log.json` later in the run, the short log cannot reach the artifact.
If generate.py prints `ABORT: the log has N entries but the previously published
page had M`, the same rule applies: stop, diagnose, publish nothing.

### Writing the log back to the database

Do this AFTER generate.py has produced `new_log.json`, and BEFORE or after the
publish — but never skip it, or the two copies drift apart:

1. `python3 db_sync.py split new_log.json writeback --since=<the current month>`
   It writes one `writeback/<YYYY-MM>.json` per month and prints them. Older
   months normally do not change; include one only if a late result was graded
   into it, in which case drop `--since`.
2. For each file, `ArtifactData` `set` with collection `log`, `doc_id` the
   month, `file_path` the file, and `if_version` the version that month's
   document showed in step 1 of the recovery. Use `batch` for more than one.
   Omit `if_version` only for a month that does not exist in the database yet.
3. If a write is refused with `version_mismatch`, something else wrote that
   document. Re-read the collection, merge again, and redo the write. Do not
   force it.

Then `python3 db_sync.py check dbdocs new_log.json` as a final assurance that
the database is not behind the page.

`log.json` in the repo is a stale artefact of an earlier design. Ignore it.

## 2. Grade what is pending

Read `log.json`. For every record with `"status": "pending"` and a `date` before
today, look up the final score and set `status` to `"final"`, `result` to
`"H"`/`"D"`/`"A"`, and `score` to e.g. `"2-1"`.

A results page per division for the relevant date usually settles several at once.
Best effort only — anything you cannot confirm quickly stays pending. This must
never block the rest of the run.

## 2b. Refit the model if the ratings are stale

```bash
python3 -c "import json,datetime;r=json.load(open('ratings.json'));d=(datetime.date.today()-datetime.date.fromisoformat(r['fitted_on'])).days;print(d)"
```

If that prints more than 7, refit:

```bash
timeout 600 python3 fit_model.py
```

Expect `FIT OK`. This pulls the current season from football-data.co.uk and
refits on history plus this season.

**Do not skip this.** Stale ratings are the single largest error source in the
model -- its gap to the market roughly doubles between fresh and three months old
(see MODEL.md). It matters about twenty-four times more than any structural tweak
that has been tested. If the download fails, fit_model.py says so and falls back to
history alone; note it in your summary, because the forecasts will be degraded.

Note the refit writes ratings.json, which CANNOT be pushed back (this repo is
read-only from the sandbox). That is fine -- the refit is cheap and runs again
tomorrow. The committed ratings.json is only a starting point.

## 2c. Attach closing odds

```bash
timeout 120 python3 enrich_closing.py log.json log.json
```

Expect a line beginning `ENRICH OK`. This pulls football-data.co.uk's current-season
files for E0-E3 and attaches the OPENING and CLOSING price to any graded fixture
that does not already have them, plus the de-vigged closing probabilities and the
drift between morning and close.

Why it matters: the forecast is made at 07:00, but the closing price is sharper and
is what the BACKTEST.md benchmark was built on. Closing odds cannot be captured
live -- the market settles and disappears at full time -- so this archive is the
only way to get them. It also supplies Closing Line Value for flagged edges, which
is the fastest read on whether those flags carry any real signal.

Run it every day. It is idempotent, skips fixtures already enriched, and costs four
small file downloads. If the source is unreachable it says so and leaves the log
untouched -- never let it block the rest of the run.

## 2d. The reconstructed period (read once, then leave alone)

`reconstruction.json` holds 29 Aug to 25 Sep 2026 rebuilt from archived results
and odds, after the original 133 graded fixtures were destroyed on 26-28 Sep.
`reconstruct.py` built it, week by week, refitting before each block.

**You do not need to touch any of this on a normal run.** generate.py picks the
file up automatically from the repo and renders it in its own "Rebuilt History"
section. There is nothing to rebuild, re-read or write back.

Two rules, and they are not negotiable:

* **Never merge it into the log.** It is a backtest, not a record of what this
  tool published. generate.py aborts if an entry carrying `reconstructed: true`
  turns up in the live log, and that abort is correct -- find how it got there.
* **Never quote its numbers as the tool's track record.** The live tool ran on
  ratings up to 118 days stale through that period; the reconstruction refits
  weekly, so it scores better than the tool really did. Its own section says so.

Re-run `reconstruct.py` only if the method itself changes, and if you do, keep
the walk-forward discipline: refit on matches strictly before each block, with
the time-decay reference set to the preceding day. The script asserts this and
will refuse to write output if it is ever broken. A reconstruction that has seen
its own answers is worse than no reconstruction, because it looks fine.

## 3. Research today's fixtures

Only England's Premier League, Championship, League One, League Two. Exclude
Scottish football, the National League, and cup competitions. Watch for
postponements, and for fixture lists that misdate matches by a day -- cross-check
the date against a second source before trusting it.

### CHECK EACH DIVISION SEPARATELY. NEVER INFER ONE FROM ANOTHER.

The four divisions do not share a calendar. The Premier League being idle tells
you NOTHING about League One and League Two, and the reverse. Confirm each of the
four separately, and record in `notes` what you found for each -- four counts,
not one.

This is not a hypothetical. On 3 Oct 2026 a run checked the Premier League
schedule, found an international break, concluded "0 fixtures" for the whole
country and published an empty page. League One and League Two both played a full
Saturday programme that afternoon. A day of forecasts was lost on a reasonable-
sounding inference from the wrong division.

The 2026-27 season makes this trap worse: the September and October international
windows were merged into one 16-day break, 21 Sep to 6 Oct 2026. The Premier
League and Championship paused for it. The EFL's lower two divisions did not.
So "international break" is never on its own a reason to report zero fixtures --
say which divisions are actually paused, and check the other two anyway.

An empty day is a real outcome and must not be invented either way. The test is
whether you checked all four, not whether the answer was zero.

## Sources: priority, and the rule that nothing is load-bearing

`soccerbase.com/matches/results.sd?date=YYYY-MM-DD` lists every English
division for one date on a single page, postponements included, and is the
quickest way to satisfy the all-four-divisions rule above. It is a fixture and
result source, not an odds source.

No single source may stop the run. Every one of these can be unreachable on any
given day -- blocked by the network allowlist, bot-protected, geo-gated, or simply
down -- and the run must carry on with whatever it can reach, then state what it
could not.

Work down this list, stopping once a fixture is priced:

1. **Odds aggregators** -- oddschecker, oddspedia. One page usually prices a whole
   division. Most efficient, so try these first.
2. **Betfair exchange** -- lowest margin, so the sharpest single estimate available.
   Best quality when reachable.
3. **Individual bookmakers** -- bet365, Ladbrokes, Paddy Power, William Hill, Sky
   Bet. Bet365 is worth preferring among these: the backtest benchmark in
   BACKTEST.md was built on Bet365 prices, so using them keeps the live track
   record comparable to it.
4. **Stats and preview sites** -- sofascore, forebet, sportsgambler, sportsmole.
   Often carry a quoted price even when the books themselves are unreachable.
5. **No price found** -- leave `odds` out for that fixture. generate.py falls back
   to the model and labels it honestly. This is an acceptable outcome for a
   handful of fixtures; it is a problem when it is most of them.

Bookmaker sites in particular are heavily bot-protected and frequently refuse
automated requests. Treat a refusal as normal, move to the next source, and do not
spend the run retrying or working around it.

Report at the end: how many fixtures you priced, out of how many, and which
sources were unreachable. A run that prices 30 of 34 and says which four it could
not is doing its job. A run that stops because one site refused is not.

**Odds coverage is the single biggest driver of forecast quality.** On 1 Sep only
8 of 24 fixtures had odds; the other 16 fell back to the model alone, which
backtesting shows is the weaker forecaster (BACKTEST.md). Treat a fixture with no
odds as a gap to close, not an acceptable outcome:

- Try the division-level odds comparison page first; it usually covers most of a round.
- For anything still missing, search that specific fixture before giving up.
- If a fixture genuinely has no quoted price, leave `odds` out entirely rather than
  guessing. generate.py will fall back to the model and label it honestly.
- Report the coverage you achieved (fixtures with odds / total) in your summary.

For each fixture get the best available decimal 1X2 odds. A division-level odds
comparison page usually covers most of a round in one fetch; only fall back to
per-match lookups for gaps.

For Premier League fixtures additionally research team news: injuries,
suspensions, and rotation risk from a midweek cup tie.

## 4. Write today.json

Schema is documented at the top of `generate.py`. Minimum per fixture: `league`,
`home`, `away`, `kickoff`, `odds` (decimal H/D/A).

**On `adjust`.** This is the only lever that moves a forecast off the market
price, and it is the only thing this tool does that the market might not have
priced at 07:00. Use it sparingly and only with a concrete, stated reason — a
named player out, a confirmed suspension, an obvious rotation risk. Put the
reason in `factors` so it is visible on the card. Values are percentage points.
Never use it on a hunch, on model-versus-market disagreement, or to manufacture
an edge. If there is no specific news, leave it out.

## 5. Generate

```bash
python3 generate.py today.json log.json ratings.json out.html new_log.json
```

Requires numpy, scipy, pandas. If a dependency is missing, `pip install` it.

## 6. Publish and commit

Publish `out.html` to the artifact URL in `README.md`, passing that URL so it
updates in place. Keep the title "Fixture Edge" and omit the favicon parameter.

**The page declares the `db` capability.** Omit `capabilities` on the publish and
the stored declaration carries forward unchanged, which is what you want. Do NOT
pass `capabilities: {}` — that clears it and takes the database away from the page.

The log is persisted twice: by the write-back to the database (section above) and
by the publish itself, since `out.html` carries the log in its `fixture-edge-log`
block. No write to GitHub is possible or needed.

If the publish fails, today's forecasts are lost but the history is not, provided
the database write-back succeeded. Do the write-back even on a run whose publish
failed.

## 7. Verify before finishing

- `out.html` was published and the tool returned the same artifact URL.
- The page's date line reads today's date.
- Every month document that changed was written back, and `db_sync.py check`
  reported `DB CHECK OK`.

If publishing failed, say so plainly in the run summary. **Do not report success
without a confirmed publish** — a run that finishes in under a minute has not
done real research, and a green status with a stale page is worse than an
obvious failure.

## Never do this

- Do not create follow-up "check whether it worked" scheduled tasks. If a run
  needs investigating, investigate it in that run and report.
- Do not redesign the dashboard. Design lives in `generate.py`.
- Do not raise `MODEL_WEIGHT` without re-running the backtest. See `BACKTEST.md`.
