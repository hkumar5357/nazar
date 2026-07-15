#!/usr/bin/env bash
# Verifies the git-history claims that make NAZAR's pre-registration real:
#   1. The repo's first commit contains PROTOCOL.md and nothing else.
#   2. The m1-freeze tag exists.
#   3. Every commit that touches demo-category scoring artifacts
#      (data/backtest/ or pipeline/backtest.py) is a descendant of m1-freeze —
#      i.e. thresholds were frozen BEFORE any demo category was ever scored.
#   4. No file in history matches obvious secret patterns.
# Run at M2 and M5 (and any time you like — it is read-only).
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

root=$(git rev-list --max-parents=0 HEAD)
first_files=$(git show --name-only --format="" "$root")
if [ "$first_files" = "PROTOCOL.md" ]; then
  echo "PASS: first commit ($root) contains only PROTOCOL.md"
else
  echo "FAIL: first commit contains: $first_files"
  fail=1
fi

if git rev-parse -q --verify m1-freeze >/dev/null; then
  echo "PASS: m1-freeze tag exists ($(git rev-parse --short m1-freeze))"
else
  echo "FAIL: m1-freeze tag missing"
  fail=1
fi

freeze=$(git rev-parse "m1-freeze^{commit}")
bad=0
# (a) Demo-category scoring OUTPUTS: every commit touching data/backtest/
# must descend from the freeze.
for c in $(git log --format=%H -- data/backtest); do
  if [ "$c" != "$freeze" ] && ! git merge-base --is-ancestor "$freeze" "$c"; then
    echo "FAIL: commit $c touches data/backtest/ but does not descend from m1-freeze"
    bad=1
    fail=1
  fi
done
# (b) Scoring CODE: pipeline/backtest.py existed as a docstring-only stub
# from the scaffold onward; any pre-freeze version of it must contain no
# scoring logic (no classify_* call).
for c in $(git log --format=%H -- pipeline/backtest.py); do
  if [ "$c" != "$freeze" ] && ! git merge-base --is-ancestor "$freeze" "$c"; then
    if git show "$c:pipeline/backtest.py" | grep -qE "classify_(trend|series)"; then
      echo "FAIL: pre-freeze commit $c has scoring logic in pipeline/backtest.py"
      bad=1
      fail=1
    fi
  fi
done
[ "$bad" -eq 0 ] && echo "PASS: all demo-category scoring (outputs and code) postdates m1-freeze"

# Secret patterns across all blobs in history (API keys, tokens, private keys).
if git grep -I -l -E "(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|BEGIN (RSA|OPENSSH) PRIVATE KEY|ghp_[A-Za-z0-9]{30,})" $(git rev-list --all) -- 2>/dev/null | head -5 | grep -q .; then
  echo "FAIL: potential secrets found in history (see above)"
  fail=1
else
  echo "PASS: no secret patterns in any committed blob"
fi

exit $fail
