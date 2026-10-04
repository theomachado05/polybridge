#!/bin/sh
set -e
cd "$(dirname "$0")/.."
PY="${PY:-../../research/.venv/bin/python}"
OUT="${OUT:-../../research/live_books}"
SUF=$("$PY" -c "import sysconfig;print(sysconfig.get_config_var('EXT_SUFFIX'))")
c++ -O3 -std=c++20 -Wall -Wextra -Wpedantic -shared -fPIC -undefined dynamic_lookup -Iinclude $("$PY" -m pybind11 --includes) \
  src/stale_quote.cpp src/stale_bindings.cpp -o "$OUT/hedgecore_stale$SUF"
echo "$OUT/hedgecore_stale$SUF"
