#!/usr/bin/env bash
# Smoke test for S265: a quiz from request to retake, on a fixture document.
#
#   POST /study/quizzes builds in the background; GET polls it to ready.
#   A question shows no answer until it is answered (practice mode).
#   POST .../answers scores once and reveals; a second answer is refused.
#   POST .../finish summarises; POST .../retake holds the misses.
#   POST /study/quiz-items/{id}/to-card answers 201, 409 or 422, never 500.
#   A section that is not in the document is 404 (I-70), never the whole document.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
smoke_requires_local_model

DOC=""
TMP="$SMOKE_TMP/s265.json"
cleanup() {
    [ -n "$DOC" ] && curl -s -o /dev/null -X DELETE "$BASE/documents/$DOC?delete_notes=true" || true
}
trap cleanup EXIT

fail() { echo "FAIL: S265 -- $1"; exit 1; }
field() { python3 -c "import json,sys; d=json.load(open('$TMP')); print($1)"; }

# Its own fixture: the shared one's sections are under the builder's 300-character passage floor.
SRC="$SMOKE_TMP/s265-$$-$RANDOM.md"
cat > "$SRC" <<'FIXTURE'
# Replication notes

## Leader-based replication

In leader-based replication one replica is designated the leader, and every write from a client
is sent to it first. The leader writes the change to its local storage and then sends the change
to all of its followers as part of a replication log. Each follower applies the writes in the same
order as the leader processed them. Reads can be served by the leader or by any follower, but a
follower that lags behind can return stale data. When the leader fails, one of the followers must
be promoted to be the new leader, a process called failover.

## Quorums in leaderless replication

In leaderless replication the client sends each write to several replicas in parallel instead of
to a single leader. With n replicas, a write must be confirmed by w nodes and a read must query r
nodes. As long as w plus r is greater than n, at least one of the nodes read holds the latest
value. Read repair fixes stale values: when a client sees that a replica returned an old value,
it writes the newer value back to that replica. An anti-entropy process copies missing data
between replicas in the background.
FIXTURE
printf '\nSmoke run %s.\n' "$$-$RANDOM" >> "$SRC"
code=$(curl -s -o "$TMP" -w '%{http_code}' -X POST "$BASE/documents/ingest" -F "file=@$SRC;type=text/markdown")
rm -f "$SRC"
[ "$code" = "200" ] || [ "$code" = "201" ] || fail "fixture upload returned $code"
DOC=$(field 'd["document_id"]')
smoke_wait_complete "$DOC" || fail "the fixture did not finish ingesting"

code=$(curl -s -o "$TMP" -w '%{http_code}' -X POST "$BASE/study/quizzes" \
    -H 'Content-Type: application/json' \
    -d "{\"document_id\":\"$DOC\",\"scope_type\":\"section\",\"scope_ref\":\"no-such-section\"}")
[ "$code" = "404" ] || fail "a section outside the document returned $code"

code=$(curl -s -o "$TMP" -w '%{http_code}' -X POST "$BASE/study/quizzes" \
    -H 'Content-Type: application/json' \
    -d "{\"document_id\":\"$DOC\",\"difficulty\":\"easy\",\"question_kinds\":\"single\",\"question_count\":2}")
[ "$code" = "201" ] || fail "create returned $code: $(cat "$TMP")"
QUIZ=$(field 'd["id"]')
[ "$(field 'd["status"]')" = "building" ] || fail "a new quiz is not building"

status=building
for _ in $(seq 1 120); do
    curl -sf -m 30 -o "$TMP" "$BASE/study/quizzes/$QUIZ"
    status=$(field 'd["status"]')
    [ "$status" != "building" ] && break
    sleep 5
done
case "$status" in
    ready) ;;
    error)
        [ -n "$(field 'd["error"] or ""')" ] || fail "an errored quiz gives no reason"
        smoke_partial_skip "the model wrote no item that passed the gates: $(field 'd["error"]')"
        echo "PASS: S265 -- quiz contract (no question to answer)"
        exit 0
        ;;
    *) fail "quiz still $status after 600s" ;;
esac

QUESTIONS=$(field 'len(d["questions"])')
[ "$QUESTIONS" -ge 1 ] || fail "a ready quiz has no questions"
[ "$(field 'all(o["is_correct"] is None for o in d["questions"][0]["options"])')" = "True" ] \
    || fail "an unanswered question shows its answer"
ITEM=$(field 'd["questions"][0]["item_id"]')
OPTION=$(field 'd["questions"][0]["options"][0]["id"]')

answer() {
    curl -s -o "$TMP" -w '%{http_code}' -X POST "$BASE/study/quizzes/$QUIZ/answers" \
        -H 'Content-Type: application/json' \
        -d "{\"position\":0,\"selected_option_ids\":[\"$OPTION\"],\"confidence\":\"guess\"}"
}
code=$(answer)
[ "$code" = "200" ] || fail "answer returned $code: $(cat "$TMP")"
[ "$(field 'd["question"]["revealed"]')" = "True" ] || fail "a practice answer was not revealed"
[ "$(field 'sum(o["is_correct"] for o in d["question"]["options"])')" = "1" ] \
    || fail "a single-answer question does not reveal exactly one right option"
code=$(answer)
[ "$code" = "409" ] || fail "a second answer returned $code"

code=$(curl -s -o "$TMP" -w '%{http_code}' -X POST "$BASE/study/quizzes/$QUIZ/finish")
[ "$code" = "200" ] || fail "finish returned $code"
[ "$(field 'd["status"]')" = "complete" ] || fail "a finished quiz is not complete"
[ "$(field 'd["results"]["answered"]')" = "1" ] || fail "results do not count the one answer"

# Answered on a guess, so it is retaken whether or not it was right.
code=$(curl -s -o "$TMP" -w '%{http_code}' -X POST "$BASE/study/quizzes/$QUIZ/retake")
[ "$code" = "201" ] || fail "retake returned $code"
[ "$(field 'd["questions"][0]["item_id"]')" = "$ITEM" ] || fail "the retake does not hold the guess"

code=$(curl -s -o "$TMP" -w '%{http_code}' -X POST "$BASE/study/quiz-items/$ITEM/to-card")
case "$code" in
    201 | 409 | 422) ;;
    *) fail "to-card returned $code: $(cat "$TMP")" ;;
esac

code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/study/quizzes/no-such-quiz")
[ "$code" = "404" ] || fail "an unknown quiz returned $code"

echo "PASS: S265 -- quiz build, answer, finish, retake and to-card"
