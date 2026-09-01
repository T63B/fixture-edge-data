# Daily run — runbook

The scheduled job runs at 06:00 UTC. It is a fresh session with no memory. Follow
these steps exactly; everything needed is in this repo.

Auth: the GitHub token is in `$GITHUB_PAT`. Repo is `T63B/fixture-edge-data`.

## 1. Pull the repo

```bash
cd /tmp && rm -rf fe && git clone -q https://x-access-token:$GITHUB_PAT@github.com/T63B/fixture-edge-data.git fe && cd fe
```

If git is blocked, fall back to the contents API per file (`GET /repos/T63B/fixture-edge-data/contents/<file>`,
base64-decode the `content` field, and keep the `sha` for writing back).

## 1b. Prove you can write, before doing anything else

Immediately after cloning, append one line to `RUNLOG.md` and push it:

```bash
echo "$(date -u +%FT%TZ) run started" >> RUNLOG.md
git config user.email fixture-edge@localhost && git config user.name "Fixture Edge"
git add RUNLOG.md && git commit -qm "runlog: start $(date -u +%F)" && git push -q origin HEAD:main && echo "WRITE OK" || echo "WRITE FAILED"
```

This takes seconds and settles the single most important question early: whether
this environment can write to the repo at all. If it prints WRITE FAILED, capture
the exact error, keep going with the rest of the run, and record the error in your
final summary — a run that can publish but not commit is still worth having.

At the END of the run, append a result line to `RUNLOG.md` and push it with the
log, recording for each step whether it succeeded: clone, grading, fixtures found,
odds found, generate.py output, artifact publish, log push. Include error text
verbatim for anything that failed. This file is the only way anyone can see what
happened inside a run afterwards, so write it as if the reader has no other
information -- because they do not.

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

Then write the log back:

```bash
cp new_log.json log.json
git add -A && git commit -qm "Fixture Edge $(date -u +%F)" && git push -q
```

## 7. Verify before finishing

- `out.html` was published and the tool returned the same artifact URL.
- `log.json` on the default branch shows today's commit.
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
