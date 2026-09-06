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
Exits 0 with an empty array if no block is found, so a first run still proceeds.
"""
import json, re, sys

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


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "log.json"
    try:
        html = open(src, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print("EXTRACT: could not read %s (%s) -- starting from an empty log" % (src, e))
        json.dump([], open(out, "w"))
        return

    m = re.search(
        r'<script[^>]*id=["\']fixture-edge-log["\'][^>]*>(.*?)</script>',
        html, re.DOTALL)
    if not m:
        print("EXTRACT: no fixture-edge-log block found -- starting from an empty log")
        json.dump([], open(out, "w"))
        return

    try:
        log = json.loads(m.group(1).strip())
        if not isinstance(log, list):
            raise ValueError("not a list")
    except Exception as e:
        print("EXTRACT: log block present but unparseable (%s) -- starting empty" % e)
        json.dump([], open(out, "w"))
        return

    log, removed = dedupe(log)

    json.dump(log, open(out, "w"), indent=1)
    pending = sum(1 for x in log if x.get("status") == "pending")
    final = sum(1 for x in log if x.get("status") == "final")
    extra = " (%d duplicate%s dropped)" % (removed, "" if removed == 1 else "s") if removed else ""
    print("EXTRACT OK: %d entries recovered (%d final, %d pending)%s -> %s"
          % (len(log), final, pending, extra, out))

main()
