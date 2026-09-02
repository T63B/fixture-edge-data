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

    json.dump(log, open(out, "w"), indent=1)
    pending = sum(1 for x in log if x.get("status") == "pending")
    final = sum(1 for x in log if x.get("status") == "final")
    print("EXTRACT OK: %d entries recovered (%d final, %d pending) -> %s"
          % (len(log), final, pending, out))

main()
