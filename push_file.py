#!/usr/bin/env python3
"""Write a file back to this repo via the GitHub contents API.

WHY THIS EXISTS: `git push` has never once succeeded from a scheduled run,
while `git clone` works fine. A clone is a GET; a push is a POST to a different
endpoint, and the sandbox proxy appears to permit the first and not the second.
The contents API is a third route, and it is the one that demonstrably worked
on 30 Aug. So this is the supported write path -- do not replace it with
`git push` without evidence that push now works.

Usage:
    python3 push_file.py <local_file> <path_in_repo> "<commit message>"

Prints exactly one line starting PUSH OK or PUSH FAILED, and exits non-zero on
failure, so the caller cannot miss it.
"""
import base64, json, os, sys, urllib.request, urllib.error

REPO = "T63B/fixture-edge-data"
API = "https://api.github.com/repos/%s/contents/" % REPO
TIMEOUT = 30


def _req(url, method="GET", payload=None, token=None):
    r = urllib.request.Request(url, method=method)
    r.add_header("Authorization", "Bearer %s" % token)
    r.add_header("Accept", "application/vnd.github+json")
    data = None
    if payload is not None:
        r.add_header("Content-Type", "application/json")
        data = json.dumps(payload).encode()
    return urllib.request.urlopen(r, data, timeout=TIMEOUT)


def main():
    if len(sys.argv) < 4:
        print("PUSH FAILED: usage: push_file.py <local> <repo_path> <message>")
        sys.exit(2)
    local, path, msg = sys.argv[1], sys.argv[2], sys.argv[3]

    token = os.environ.get("GITHUB_PAT")
    if not token:
        print("PUSH FAILED: GITHUB_PAT is not set in this environment")
        sys.exit(1)

    try:
        blob = open(local, "rb").read()
    except OSError as e:
        print("PUSH FAILED: cannot read local file %s: %s" % (local, e))
        sys.exit(1)

    sha = None
    try:
        with _req(API + path, token=token) as r:
            sha = json.load(r).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print("PUSH FAILED: reading %s returned %s %s"
                  % (path, e.code, e.read()[:200]))
            sys.exit(1)
    except Exception as e:
        print("PUSH FAILED: network error reading %s: %s" % (path, e))
        sys.exit(1)

    body = {"message": msg, "content": base64.b64encode(blob).decode()}
    if sha:
        body["sha"] = sha

    try:
        with _req(API + path, "PUT", body, token) as r:
            out = json.load(r)
        print("PUSH OK: %s -> commit %s (%d bytes)"
              % (path, out["commit"]["sha"][:8], len(blob)))
    except urllib.error.HTTPError as e:
        print("PUSH FAILED: PUT %s returned %s %s"
              % (path, e.code, e.read()[:300]))
        sys.exit(1)
    except Exception as e:
        print("PUSH FAILED: network error writing %s: %s" % (path, e))
        sys.exit(1)


main()
