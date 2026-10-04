#!/bin/sh
set -e
cd "$(dirname "$0")/.."
PY="${PY:-../../research/.venv/bin/python}"
OUT="${OUT:-../../research/live_books}"
OBJ="${OBJ:-build/simdjson-native.o}"
SUF=$("$PY" -c "import sysconfig;print(sysconfig.get_config_var('EXT_SUFFIX'))")
FLAGS="-O3 -march=native -std=c++20 -fPIC"
SSL="${SSL:-$(brew --prefix openssl@3 2>/dev/null || echo /usr)}"
if [ -f "$SSL/lib/libssl.a" ] && [ -f "$SSL/lib/libcrypto.a" ]; then
  SSLLIBS="$SSL/lib/libssl.a $SSL/lib/libcrypto.a"
else
  SSLLIBS="-L$SSL/lib -lssl -lcrypto -Wl,-rpath,$SSL/lib"
fi
PYINC=$("$PY" -m pybind11 --includes)
c++ $FLAGS -Wall -Wextra -Wpedantic -shared -undefined dynamic_lookup -Iinclude $PYINC \
  src/stale_quote.cpp src/stale_bindings.cpp -o "$OUT/hedgecore_stale$SUF"
echo "$OUT/hedgecore_stale$SUF"
mkdir -p "$(dirname "$OBJ")"
if [ ! -f "$OBJ" ] || [ third_party/simdjson/simdjson.cpp -nt "$OBJ" ]; then
  c++ $FLAGS -DNDEBUG -Ithird_party/simdjson -c third_party/simdjson/simdjson.cpp -o "$OBJ"
fi
c++ $FLAGS -DNDEBUG -Wall -Wextra -Wpedantic -shared -undefined dynamic_lookup -Iinclude -Ithird_party/simdjson $PYINC \
  -I"$SSL/include" src/stale_quote.cpp src/book_engine.cpp src/ws_feed.cpp src/book_bindings.cpp "$OBJ" \
  $SSLLIBS -o "$OUT/hedgecore_book$SUF"
echo "$OUT/hedgecore_book$SUF"
