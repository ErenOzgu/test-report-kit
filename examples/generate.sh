#!/usr/bin/env bash
# Regenerates the committed example outputs from the committed example runs.
#   examples/generate.sh           write examples/out/*
#   examples/generate.sh --check   fail if what is committed differs from what the tool prints today
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
out="$here/out"
mode="${1:-write}"
if [[ "$mode" != "write" && "$mode" != "--check" ]]; then
  echo "usage: $0 [--check]" >&2
  exit 2
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$root"
trk=(python -m test_report_kit)

before=(examples/runs/before/*.xml)
after=(examples/runs/after/*.xml)

"${trk[@]}" report "${before[@]}" --title "Checkout service: 4 runs of one commit" -o "$tmp/report.md"
"${trk[@]}" report "${before[@]}" --title "Checkout service: 4 runs of one commit" --format html -o "$tmp/report.html"
"${trk[@]}" report "${before[@]}" --title "Checkout service: 4 runs of one commit" --format json -o "$tmp/report.json"
"${trk[@]}" report "${before[@]}" "${after[@]}" --title "Checkout service: two commits" -o "$tmp/report-two-commits.md"
"${trk[@]}" compare --before "${before[@]}" --after "${after[@]}" -o "$tmp/compare.md"
"${trk[@]}" report examples/runs/surefire/*.xml --title "Surefire: one run with a retry" -o "$tmp/surefire.md"
{
  echo '$ test-report-kit flaky examples/runs/before/*.xml --fail-on both'
  status=0
  "${trk[@]}" flaky "${before[@]}" --fail-on both || status=$?
  echo "(exit status $status)"
} >"$tmp/flaky.txt"
{
  echo '$ test-report-kit flaky examples/runs/before/*.xml --allowlist examples/allowlist.toml --today 2026-10-18'
  status=0
  "${trk[@]}" flaky "${before[@]}" --allowlist examples/allowlist.toml --today 2026-10-18 || status=$?
  echo "(exit status $status)"
} >"$tmp/flaky-allowlist.txt"

if [[ "$mode" == "--check" ]]; then
  diff -ru "$out" "$tmp"
  echo "examples/out is up to date"
else
  mkdir -p "$out"
  cp "$tmp"/* "$out"/
  echo "wrote the files in examples/out"
fi
