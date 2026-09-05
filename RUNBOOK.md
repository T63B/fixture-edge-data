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

## 1b. Recover the log from the published page

**The repo is READ-ONLY from the scheduled sandbox.** Clone works; every write is
refused, `git push` and the GitHub contents API alike. This is a permission tier
on the sandbox's repo attachment, not a token or network problem, and it cannot
be worked around from inside a run. Do not spend time trying.

So the log does not live in the repo. It lives in the published page. `generate.py`
embeds the entire log in a `<script id="fixture-edge-log">` block, so yesterday's
page holds the full history, and publishing today's page is what persists it.

Recover it like this:

1. Use the Artifact tool's `read` action on the dashboard URL in README.md and save
   the returned HTML to `prev.html`.
2. `python3 extract_log.py prev.html log.json`

You should see a line beginning `EXTRACT OK`. If the read fails or no block is
found, extract_log.py writes an empty log and the run continues -- but say so
clearly in your summary, because it means that day's history is starting over.

`log.json` in the repo is a stale artefact of an earlier design. Ignore it.

## 2. Grade what is pending

Read `log.json`. For every record with `"status": "pending"` and a `date` before
today, look up the final score and set `status` to `"final"`, `result` to
`"H"`/`"D"`/`"A"`, and `score` to e.g. `"2-1"`.

A results page per division for the relevant date usually settles several at once.
Best effort only — anything you cannot confirm quickly stays pending. This must
never block the rest of the run.

## 3. Research today's fixtures

Only England's Premier League, Championship, League One, League Two. Exclude
Scottish football, the National League, and cup competitions. Watch for
postponements, and for fixture lists that misdate matches by a day — cross-check
the date against a second source before trusting it.

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

The log is persisted **by the publish itself** -- `out.html` contains the updated
log in its `fixture-edge-log` block. There is nothing further to commit, and no
write to GitHub is possible or needed.

This makes the publish the single critical step of the run. If it fails, the day's
predictions AND the accumulated history are both lost, so confirm it succeeded and
say plainly in your summary if it did not.

## 7. Verify before finishing

- `out.html` was published and the tool returned the same artifact URL.
- The publish returned the same artifact URL, and the page now shows today's date.
- The page's date line reads today's date.

If publishing failed, say so plainly in the run summary. **Do not report success
without a confirmed publish** — a run that finishes in under a minute has not
done real research, and a green status with a stale page is worse than an
obvious failure.

## Never do this

- Do not create follow-up "check whether it worked" scheduled tasks. If a run
  needs investigating, investigate it in that run and report.
- Do not redesign the dashboard. Design lives in `generate.py`.
- Do not raise `MODEL_WEIGHT` without re-running the backtest. See `BACKTEST.md`.
