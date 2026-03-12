#!/usr/bin/env bash
# S108 smoke: verify TeachbackPanel voice input compiles correctly
# Web Speech API is browser-only so runtime testing requires a browser;
# this script verifies TypeScript types and build integrity.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "S108 [1/2]: TypeScript type check (SpeechRecognition types)..."
cd "${REPO_ROOT}/frontend"
npx tsc --noEmit
echo "PASS: tsc --noEmit"

echo "S108 [2/2]: Vite build (no chunk warnings)..."
npm run build 2>&1 | tee /tmp/s108-build.log
if grep -q "chunk size warning" /tmp/s108-build.log; then
  echo "FAIL: chunk size warning in build output"
  exit 1
fi
echo "PASS: vite build clean"

echo "S108: ALL CHECKS PASSED"
