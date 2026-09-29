#!/usr/bin/env python3
"""Move the prediction log between log.json and the artifact's database.

WHY THIS EXISTS
---------------
The log used to live only inside the published page. Publishing overwrites the
page, so one failed read destroyed the record: 133 graded fixtures, 29 Aug to
25 Sep 2026, gone for good. Guards now stop a run publishing over the history,
but a guard only narrows the failure -- it does not add a second copy.

So the log now lives in the artifact's own database, which publishing cannot
touch, and the page keeps its embedded copy as a secondary. Two independent
stores, either of which can rebuild the other.

SHAPE
-----
Collection `log`, one document per calendar month, id `YYYY-MM`:

    {"month": "2026-09", "count": 137, "fixtures": [ ...log entries... ]}

One document per fixture would be wrong: the database holds at most 5,000
documents and this is an unbounded, growing stream. Monthly buckets are about
a dozen documents a year, each well inside the 256 KiB document limit (a busy
month is roughly 200 fixtures, about 80 KB).

USAGE
-----
    python3 db_sync.py merge <docs_dir> log.json
        Assemble log.json from documents saved by an ArtifactData read
        (`list` on collection `log` with out_dir=<docs_dir>). Also writes
        log_floor.txt, so generate.py's shrink guard applies to the database
        copy exactly as it does to the page copy.

    python3 db_sync.py split log.json <out_dir> [--since YYYY-MM]
        Write one <out_dir>/<YYYY-MM>.json per month, each a complete document
        body ready to hand to ArtifactData `set` via file_path. Prints one line
        per month so the run knows which documents to write back; --since
        limits output to recent months, since older ones rarely change.

    python3 db_sync.py check <docs_dir> log.json
        Compare the database copy against a log without writing anything.
        Prints DB CHECK OK, or names the discrepancy and exits 2.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_log import dedupe, write_floor

COLLECTION = "log"


def month_of(entry):
    d = str(entry.get("date") or "")
    m = re.match(r"(\d{4})-(\d{2})", d)
    return m.group(0) if m else None


def load_docs(docs_dir):
    """Read the JSON documents an ArtifactData read saved.

    Accepts either <docs_dir>/log/2026-09.json (the documented layout, where
    the collection path becomes a subdirectory) or <docs_dir>/2026-09.json,
    so a run does not have to care which it got.
    """
    roots = [os.path.join(docs_dir, COLLECTION), docs_dir]
    seen, docs = set(), []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if not name.endswith(".json") or name in seen:
                continue
            path = os.path.join(root, name)
            try:
                body = json.load(open(path))
            except Exception as e:
                sys.exit("ABORT: %s is not readable JSON (%s). The database copy "
                         "is the primary store -- do not proceed on a partial "
                         "read." % (path, e))
            if not isinstance(body, dict):
                continue
            seen.add(name)
            docs.append((name[:-5], body))
    return docs


def fixtures_from(docs):
    out = []
    for doc_id, body in docs:
        fx = body.get("fixtures")
        if not isinstance(fx, list):
            sys.exit("ABORT: document %s has no `fixtures` list. Refusing to "
                     "rebuild the log from a malformed document." % doc_id)
        declared = body.get("count")
        if isinstance(declared, int) and declared != len(fx):
            sys.exit("ABORT: document %s declares %d fixtures but carries %d. "
                     "The read was probably truncated; retry it."
                     % (doc_id, declared, len(fx)))
        out.extend(fx)
    return out


def cmd_merge(docs_dir, out_p):
    docs = load_docs(docs_dir)
    log = fixtures_from(docs)
    log, removed = dedupe(log)
    log.sort(key=lambda m: (str(m.get("date") or ""), str(m.get("league") or ""),
                            str(m.get("home") or "")))
    json.dump(log, open(out_p, "w"), indent=1)
    write_floor(out_p, len(log))
    final = sum(1 for x in log if x.get("status") == "final")
    print("DB MERGE OK: %d entries from %d month document%s (%d final, %d pending)%s -> %s"
          % (len(log), len(docs), "" if len(docs) == 1 else "s", final,
             len(log) - final, "" if not removed else
             " (%d duplicate%s dropped)" % (removed, "" if removed == 1 else "s"),
             out_p))
    if not docs:
        print("NOTE: the database holds no log documents yet. If this is not the "
              "first run after the migration, STOP -- do not publish, and do not "
              "write an empty log back.")


def cmd_split(log_p, out_dir, since=None):
    log = json.load(open(log_p))
    buckets = {}
    undated = 0
    for m in log:
        k = month_of(m)
        if not k:
            undated += 1
            continue
        buckets.setdefault(k, []).append(m)
    if undated:
        print("WARNING: %d entries have no usable date and were left out." % undated)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for k in sorted(buckets):
        if since and k < since:
            continue
        body = {"month": k, "count": len(buckets[k]), "fixtures": buckets[k]}
        path = os.path.join(out_dir, k + ".json")
        json.dump(body, open(path, "w"), indent=1)
        size = os.path.getsize(path)
        if size > 240 * 1024:
            print("WARNING: %s is %d bytes, close to the 256 KiB document limit."
                  % (path, size))
        written.append((k, len(buckets[k]), size, path))
    print("DB SPLIT OK: %d month document%s ready" % (len(written), "" if len(written) == 1 else "s"))
    for k, n, size, path in written:
        print("  %s  %4d fixtures  %6d bytes  %s" % (k, n, size, path))
    print("Write each back with ArtifactData `set`, collection `%s`, doc_id the "
          "month, file_path the file above, and if_version the version you read."
          % COLLECTION)


def cmd_check(docs_dir, log_p):
    db = fixtures_from(load_docs(docs_dir))
    db, _ = dedupe(db)
    log, _ = dedupe(json.load(open(log_p)))
    if len(db) < len(log):
        sys.exit("DB CHECK FAILED: the database holds %d entries, the log %d. "
                 "The database copy is behind -- write it back before relying on it."
                 % (len(db), len(log)))
    print("DB CHECK OK: database %d entries, log %d." % (len(db), len(log)))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    since = None
    for a in sys.argv[1:]:
        if a.startswith("--since="):
            since = a.split("=", 1)[1]
    if len(args) < 3:
        print(__doc__)
        sys.exit(1)
    cmd = args[0]
    if cmd == "merge":
        cmd_merge(args[1], args[2])
    elif cmd == "split":
        cmd_split(args[1], args[2], since)
    elif cmd == "check":
        cmd_check(args[1], args[2])
    else:
        sys.exit("unknown command %r (merge, split, check)" % cmd)


main()
