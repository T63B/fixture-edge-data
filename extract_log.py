#!/usr/bin/env python3
"""Pull the prediction log out of a previously published Fixture Edge page.

WHY THIS EXISTS: the scheduled sandbox has READ-ONLY access to the GitHub repo.
Clone works; every write (git push and the contents API alike) is refused. So the
log cannot live in the repo. It lives in the published page instead: generate.py
embeds the whole log as JSON in a <script id="fixture-edge-log"> block, and the
page is republished every run. Reading yesterday's page therefore recovers the
full history, and publishing today's page persists it. Both paths work from the
sandbox; GitHub writes do not.

Usage:
    python3 extract_log.py <saved_page.html> [out.json]

Writes the log array to out.json (default log.json) and prints a summary line.

FAILURE IS FATAL, DELIBERATELY. This script used to shrug off a missing or
unreadable log block and carry on with an empty array, on the reasoning that a
first run has no history to lose. That convenience destroyed the track record:
between 26 and 28 Sep 2026 a scheduled run could not read the previous page,
started from nothing, published it, and erased 133 graded fixtures -- and since
every publish overwrites the page, and the page is the only copy, there was no
way back. So any failure now exits 2 and writes no output file, which stops the
run before it can publish over the history. Losing a day of forecasts is cheap;
losing the record is not. Pass --allow-empty only to bootstrap a genuinely new
page from nothing.

It also writes log_floor.txt beside the output: the number of entries recovered.
generate.py refuses to build a page with fewer than that, so a log that is
emptied or truncated after this point still cannot reach the artifact.
"""
import json, os, re, sys

def _squash(name):
    """Reduce a club name to a comparable core: 'Cardiff City' -> 'cardiff'."""
    n = re.sub(r"[^a-z0-9 ]", "", str(name).lower()).strip()
    n = re.sub(r"\s+(fc|afc|town|city|united|rovers|wanderers|athletic|county|albion|hotspur)$", "", n)
    return re.sub(r"\s+", "", n)


def dedupe(log):
    """Drop repeat entries for the same fixture, keeping the richer record.

    Early runs keyed the log on literal text, so the same match could be logged
    twice under different spellings ("QPR v Cardiff" and "QPR v Cardiff City").
    Those stale duplicates double-count a result in the track record. Running this
    on every load means the log heals itself rather than needing a manual clean.
    """
    best = {}
    order = []
    for m in log:
        if not isinstance(m, dict) or not m.get("date"):
            continue
        k = (m.get("date"), _squash(m.get("home")), _squash(m.get("away")))
        if k not in best:
            best[k] = m
            order.append(k)
            continue
        # Prefer a graded record over a pending one, then one carrying market odds.
        cur = best[k]
        def score(x):
            return (1 if x.get("status") == "final" else 0) + (1 if x.get("market_pct") else 0)
        if score(m) > score(cur):
            best[k] = m
    return [best[k] for k in order], len(log) - len(order)


def migrate_methodology(log):
    """Make the forecast field hold the MODEL's view rather than the market's.

    Until 19 Sep 2026 the published forecast WAS the de-vigged market price, so
    `model_pct` held a copy of `market_pct`. The tool now publishes its own model.
    The independent model's prediction was recorded throughout in `model_raw_pct`,
    so the history can be rescored honestly rather than thrown away.

    Old-design entries are identified by the forecast matching the market almost
    exactly. Idempotent, and a no-op where the model genuinely agreed with the price.
    """
    n = 0
    for m in log:
        raw, mk, fc = m.get("model_raw_pct"), m.get("market_pct"), m.get("model_pct")
        if not (raw and mk and fc):
            continue
        if (max(abs(fc[k] - mk[k]) for k in ("H", "D", "A")) < 0.6
                and max(abs(raw[k] - mk[k]) for k in ("H", "D", "A")) >= 0.6):
            m["model_pct"] = dict(raw)
            n += 1
    return n


def write_floor(out, n):
    """Record how many entries were recovered, for generate.py's shrink guard."""
    path = os.path.join(os.path.dirname(os.path.abspath(out)) or ".", "log_floor.txt")
    open(path, "w").write(str(n))


def fail(msg):
    """Stop the run. No output file is written, so nothing downstream can publish."""
    print("EXTRACT FAILED: %s" % msg)
    print("STOP HERE. Do not publish: the page is the only copy of the track record,")
    print("and publishing a page built without it would erase the history for good.")
    print("Diagnose the read (artifact URL, permissions, network) and re-run.")
    print("Only if this is a deliberately fresh page, re-run with --allow-empty.")
    sys.exit(2)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    allow_empty = "--allow-empty" in sys.argv
    src = args[0]
    out = args[1] if len(args) > 1 else "log.json"

    def bootstrap(reason):
        if not allow_empty:
            fail(reason)
        print("EXTRACT: %s -- starting from an empty log (--allow-empty given)" % reason)
        json.dump([], open(out, "w"))
        write_floor(out, 0)
        sys.exit(0)

    try:
        html = open(src, encoding="utf-8", errors="replace").read()
    except OSError as e:
        bootstrap("could not read %s (%s)" % (src, e))

    m = re.search(
        r'<script[^>]*id=["\']fixture-edge-log["\'][^>]*>(.*?)</script>',
        html, re.DOTALL)
    if not m:
        bootstrap("no fixture-edge-log block found in %s" % src)

    try:
        log = json.loads(m.group(1).strip())
        if not isinstance(log, list):
            raise ValueError("not a list")
    except Exception as e:
        # A truncated or corrupted page is NOT a reason to start over -- it is the
        # exact shape of the failure that cost the record once already.
        fail("the log block is present but unparseable (%s). The page was probably "
             "truncated or partially read; the history is likely still intact in the "
             "artifact, so retry the read rather than rebuilding from nothing." % e)

    # The page declares how many entries it carries. If we parsed fewer, the read
    # was short even though the JSON happened to close cleanly.
    declared = re.search(r'data-count=["\'](\d+)["\']', m.group(0))
    if declared:
        n = int(declared.group(1))
        if len(log) < n:
            fail("the page declares %d log entries but only %d parsed -- the read was "
                 "truncated. The history is intact in the artifact; retry the read."
                 % (n, len(log)))

    log, removed = dedupe(log)
    migrated = migrate_methodology(log)

    json.dump(log, open(out, "w"), indent=1)
    write_floor(out, len(log))
    pending = sum(1 for x in log if x.get("status") == "pending")
    final = sum(1 for x in log if x.get("status") == "final")
    extra = ("" if not migrated else " (%d rescored to the model)" % migrated) + " (%d duplicate%s dropped)" % (removed, "" if removed == 1 else "s") if removed else ("" if not migrated else " (%d rescored to the model)" % migrated)
    print("EXTRACT OK: %d entries recovered (%d final, %d pending)%s -> %s"
          % (len(log), final, pending, extra, out))


# db_sync.py imports dedupe() and write_floor() from here, so the script must
# not run when it is imported -- without this guard it ran main() on the
# importer's argv and aborted the run with a confusing EXTRACT FAILED.
if __name__ == "__main__":
    main()
