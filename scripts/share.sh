#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
REPLAY="${REPLAY:-backend/replays/us-recession-in-2025-weekend-2025-04-04.jsonl}"
SPEED="${SPEED:-3600}"
REPLAY_PRICES="${REPLAY_PRICES-recorded}"
BACKEND_PORT=8000
WEB_PORT=3000

die() { echo "make share: $*" >&2; exit 1; }
env_val() {
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}$1=//p" "$ENV_FILE" | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

[ -f "$ENV_FILE" ] || die "no .env at the repo root (copy .env.example)."
SECRET="$(env_val AGENT_TOOL_SECRET)"
[ -n "$SECRET" ] || die "AGENT_TOOL_SECRET is empty in .env. Tunnel mode needs it: the backend refuses every proxied write without it. Set it to a long random value (openssl rand -hex 24)."

AUTH=""
if [ -z "${SHARE_NO_NGROK:-}" ]; then
  AUTH="$(env_val NGROK_BASIC_AUTH)"
  [ -n "$AUTH" ] || die "NGROK_BASIC_AUTH is not set in .env (format user:password). Refusing to open a public URL without a password."
  case "$AUTH" in
    *:*) ;;
    *) die "NGROK_BASIC_AUTH must be user:password." ;;
  esac
  user="${AUTH%%:*}"; pass="${AUTH#*:}"
  [ -n "$user" ] || die "NGROK_BASIC_AUTH has an empty user (format user:password)."
  [ "${#pass}" -ge 8 ] && [ "${#pass}" -le 128 ] || die "NGROK_BASIC_AUTH password must be 8 to 128 characters (ngrok's rule)."
  command -v ngrok >/dev/null || die "ngrok is not installed (brew install ngrok), then: ngrok config add-authtoken <token>."
  ngrok config check >/dev/null 2>&1 || die "ngrok config check failed: run ngrok config add-authtoken <token> first."
fi

for p in $BACKEND_PORT $WEB_PORT 4040; do
  if lsof -ti ":$p" -sTCP:LISTEN >/dev/null 2>&1; then
    [ "$p" = 4040 ] && [ -n "${SHARE_NO_NGROK:-}" ] && continue
    die "port $p is busy (stop make dev / another ngrok first)."
  fi
done

pids=()
cleanup() { trap - INT TERM EXIT; for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup INT TERM EXIT

ENVARG=(--env-file "$ENV_FILE")
( cd "$ROOT/backend" && POLYBRIDGE_REPLAY_PATH="$ROOT/$REPLAY" POLYBRIDGE_REPLAY_SPEED="$SPEED" \
    POLYBRIDGE_REPLAY_PRICES="$REPLAY_PRICES" exec uv run --group engine "${ENVARG[@]}" \
    uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT ) &
pids+=($!)

echo "make share: building the web app in tunnel mode (NEXT_PUBLIC_API_URL=/api) ..."
( cd "$ROOT/web" && NEXT_PUBLIC_API_URL=/api pnpm build >/dev/null ) || die "pnpm build failed (run: cd web && NEXT_PUBLIC_API_URL=/api pnpm build)."
( cd "$ROOT/web" && NEXT_PUBLIC_API_URL=/api AGENT_TOOL_SECRET="$SECRET" exec pnpm exec next start -H 127.0.0.1 -p $WEB_PORT ) &
pids+=($!)

for _ in $(seq 1 120); do
  curl -sf -o /dev/null "http://127.0.0.1:$BACKEND_PORT/health" && curl -sf -o /dev/null "http://127.0.0.1:$WEB_PORT/" && break
  sleep 1
done
curl -sf -o /dev/null "http://127.0.0.1:$WEB_PORT/api/health" || die "the web server does not proxy /api/health to the backend."
echo "make share: backend :$BACKEND_PORT and web :$WEB_PORT up (tunnel mode, /api proxied)."

if [ -n "${SHARE_NO_NGROK:-}" ]; then
  echo "make share: SHARE_NO_NGROK set; open http://localhost:$WEB_PORT (Ctrl-C stops)."
  wait
  exit 0
fi

ngrok http $WEB_PORT --basic-auth "$AUTH" --log=stdout --log-level=warn >/dev/null &
pids+=($!)
URL=""
for _ in $(seq 1 30); do
  URL="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c 'import json,sys
try:
    t=[x["public_url"] for x in json.load(sys.stdin).get("tunnels",[]) if x.get("public_url","").startswith("https://")]
    print(t[0] if t else "")
except Exception:
    print("")' || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || die "ngrok did not report a public URL (see http://127.0.0.1:4040)."
HOST="${URL#https://}"
echo
echo "  Public URL : $URL   (ngrok basic auth: the user:password in NGROK_BASIC_AUTH)"
echo "  Voice      : run once so the ElevenLabs widget accepts this host:"
echo "               PUBLIC_WEB_HOST=$HOST make voice-agent"
echo "  Stop       : Ctrl-C (stops ngrok, web and backend)"
echo
wait
