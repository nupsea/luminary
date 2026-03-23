#!/usr/bin/env bash
# Smoke test for S140: Code Execution Sandbox with Predict-then-Run
# Requires a running backend at localhost:7820
set -euo pipefail

BASE="http://localhost:7820"

echo "--- S140 smoke tests ---"

# Test 1: Basic Python execution
RESP=$(curl -sf -X POST "$BASE/code/execute" \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"hello\")", "language": "python"}')
python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['exit_code'] == 0, f'exit_code={d[\"exit_code\"]}'
assert 'hello' in d['stdout'], f'stdout={d[\"stdout\"]!r}'
print('  stdout:', repr(d['stdout']))
" <<< "$RESP"
echo "PASS: POST /code/execute python hello"

# Test 2: Prediction comparison (correct)
RESP2=$(curl -sf -X POST "$BASE/code/execute" \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"hello\")", "language": "python", "expected_output": "hello"}')
python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['prediction_correct'] is True, f'expected True, got {d[\"prediction_correct\"]}'
print('  prediction_correct:', d['prediction_correct'])
" <<< "$RESP2"
echo "PASS: POST /code/execute prediction_correct=True"

# Test 3: Prediction comparison (wrong)
RESP3=$(curl -sf -X POST "$BASE/code/execute" \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"hello\")", "language": "python", "expected_output": "world"}')
python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['prediction_correct'] is False, f'expected False, got {d[\"prediction_correct\"]}'
assert d['prediction_diff'], 'expected non-empty prediction_diff'
print('  prediction_correct:', d['prediction_correct'])
" <<< "$RESP3"
echo "PASS: POST /code/execute prediction_correct=False with diff"

# Test 4: Timeout enforcement
RESP4=$(curl -sf -X POST "$BASE/code/execute" \
  -H "Content-Type: application/json" \
  -d '{"code": "import time; time.sleep(60)", "language": "python", "timeout_ms": 2000}')
python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['exit_code'] != 0, f'expected non-zero exit_code, got {d[\"exit_code\"]}'
print('  exit_code:', d['exit_code'])
" <<< "$RESP4"
echo "PASS: POST /code/execute timeout enforced"

echo "--- S140 smoke tests PASSED ---"
