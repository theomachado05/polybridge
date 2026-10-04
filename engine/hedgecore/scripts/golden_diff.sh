#!/usr/bin/env bash
set -euo pipefail
base="${1:?base commit}"
root="$(git rev-parse --show-toplevel)"
eng="$root/engine/hedgecore"
tmp="$(mktemp -d)"
trap 'git -C "$root" worktree remove --force "$tmp/base" >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
git -C "$root" worktree add --detach "$tmp/base" "$base" >/dev/null
mkdir -p "$tmp/base_tests"
cp "$eng/tests/golden_render.hpp" "$eng/tests/golden_dump.cpp" "$eng/tests/tick_helpers.hpp" "$tmp/base_tests/"
CXX="${CXX:-c++}"
FLAGS=(-std=c++20 -O3 -DNDEBUG)
build() {
  "$CXX" "${FLAGS[@]}" -I"$1/include" -I"$2" "$1/src/engine.cpp" "$1/src/replay.cpp" "$2/golden_dump.cpp" -o "$3"
}
build "$tmp/base/engine/hedgecore" "$tmp/base_tests" "$tmp/dump_base"
build "$eng" "$eng/tests" "$tmp/dump_head"
"$tmp/dump_base" > "$tmp/base.txt"
"$tmp/dump_head" > "$tmp/head.txt"
if cmp -s "$tmp/base.txt" "$tmp/head.txt"; then
  echo "golden: identical to $base ($(wc -l < "$tmp/head.txt") lines, $(grep -c '^family' "$tmp/head.txt") families)"
else
  echo "golden: DIFFERS from $base" >&2
  diff "$tmp/base.txt" "$tmp/head.txt" | head -20 >&2
  exit 1
fi
