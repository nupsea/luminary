#!/usr/bin/env bash
# S244 smoke: GET /blog/drafts lists collected-but-unpublished notes.
#
# `blog` is a full-mode surface, so this is a no-op against a public build --
# the route is not mounted there and the script says so rather than failing.
set -euo pipefail

BASE="http://localhost:7820"

CT=$(curl -s -o /dev/null -w "%{content_type}" -m 10 "${BASE}/blog/config" || true)
case "$CT" in
  application/json*) ;;
  *)
    echo "SKIP: S244 -- /blog is not mounted (public mode); nothing to check"
    exit 0
    ;;
esac

for kind in blog thoughts; do
  BODY=$(curl -sf -m 30 "${BASE}/blog/drafts?kind=${kind}")
  echo "$BODY" | python3 -c "
import sys, json
rows = json.load(sys.stdin)
assert isinstance(rows, list), f'expected a list, got {type(rows).__name__}'
for r in rows:
    for f in ('note_id', 'title', 'slug', 'excerpt'):
        assert f in r, f'draft row missing {f}: {r}'
    assert r['slug'], 'slug must be non-empty -- it is the published-or-not key'
print(f'  ${kind}: {len(rows)} draft(s)')
" || { echo "FAIL: S244 -- /blog/drafts?kind=${kind} shape wrong"; exit 1; }
done

# A draft must never duplicate something already on the site: the two listings
# are keyed on the same slug, so an overlap means the filter stopped working.
python3 - "$BASE" <<'PY' || exit 1
import json, sys, urllib.request

base = sys.argv[1]
def get(path):
    with urllib.request.urlopen(f"{base}{path}", timeout=30) as r:
        return json.load(r)

for kind in ("blog", "thoughts"):
    drafts = {d["slug"] for d in get(f"/blog/drafts?kind={kind}")}
    posts = {p["slug"] for p in get(f"/blog/posts?kind={kind}")}
    overlap = drafts & posts
    assert not overlap, f"{kind}: slug in BOTH drafts and posts: {sorted(overlap)}"
print("  drafts and published posts are disjoint")
PY

CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 10 "${BASE}/blog/drafts?kind=wat")
[ "$CODE" = "422" ] || { echo "FAIL: S244 -- bad kind returned ${CODE}, expected 422"; exit 1; }

echo "PASS: S244 -- /blog/drafts lists unpublished collected notes, disjoint from posts"
