# Share: the whole app behind one public URL

`make share` runs the demo on this laptop and publishes it at one ngrok URL, behind a password.

```
browser ──https──> ngrok (basic auth) ──> Next.js :3000 ──/api/* rewrite + X-Agent-Secret──> backend 127.0.0.1:8000
```

- **Web** is a production build with `NEXT_PUBLIC_API_URL=/api`: the page calls `/api/...` on its own origin, so there is
  one URL, no CORS, and the backend port is never exposed. `web/next.config.ts` rewrites `/api/:path*` to
  `http://127.0.0.1:8000/:path*` (override: `POLYBRIDGE_BACKEND_ORIGIN`). Without `NEXT_PUBLIC_API_URL` the page still
  calls `http://localhost:8000` directly (`make dev`, unchanged).
- **Server-side secret.** `web/src/proxy.ts` (Next.js Proxy, Node runtime, matcher `/api/:path*`) drops any
  `X-Agent-Secret` the browser sent and sets the server's own `AGENT_TOOL_SECRET`. The variable is not `NEXT_PUBLIC_`,
  is passed only to the `next start` process, and is not in `web/.next` (checked by grepping the build output for the
  value: 0 files).
- **Backend** treats every proxied call as remote (the proxy always sends a forwarding header), so its existing guard
  (`backend/app/security.py`) requires the secret on every write. Reads need nothing beyond the ngrok password.
- **SSE** (bridge streams) passes through the rewrite unbuffered: the stream sends `Cache-Control: no-cache,
  no-transform`, so Next.js does not gzip it. Checked through ngrok: events arrive continuously, about 12 a second.

## Run it

One-time setup (Theo):

1. `brew install ngrok`, then `ngrok config add-authtoken <token>` (from dashboard.ngrok.com). `ngrok config check`
   must pass.
2. In the repo-root `.env`:
   - `NGROK_BASIC_AUTH=user:password` (password 8 to 128 characters; this is the only public gate, so pick a strong one)
   - `AGENT_TOOL_SECRET=<long random value>` (`openssl rand -hex 24`)

Then:

```
make share
```

It refuses to start without either variable, builds the web app in tunnel mode, starts backend and web, opens the
tunnel, and prints:

```
  Public URL : https://<host>.ngrok-free.dev   (ngrok basic auth: the user:password in NGROK_BASIC_AUTH)
  Voice      : PUBLIC_WEB_HOST=<host>.ngrok-free.dev make voice-agent
```

Run the voice command once per new host: it adds the host to the ElevenLabs widget allowlist (next to
localhost:3000). Ctrl-C stops ngrok, web and backend. Same replay knobs as `make dev` (`REPLAY=`, `SPEED=`,
`REPLAY_PRICES=`). `SHARE_NO_NGROK=1 make share` runs the same tunnel-mode servers without ngrok, for a local check:

```
SHARE_NO_NGROK=1 make share     # in one terminal
python3 scripts/e2e_demo.py --reuse --no-screens --api-base http://localhost:3000/api   # API flow + SSE through the proxy
```

Free ngrok shows a one-time browser warning page per visitor; click through it.

## Threat model

- **Who can read:** anyone past the ngrok password. ngrok enforces basic auth before any request reaches the laptop
  (no password or a wrong one: 401 at ngrok).
- **Who can write** (create and approve proposals, start bridges, place or cancel paper orders, reset the sim account,
  call voice tools): only people past the ngrok password, because the Next.js server attaches the secret to every
  proxied call. The secret is not a second factor for those viewers; it keeps the backend closed to anything that
  reaches it without going through this proxy.
- **The backend is never exposed directly.** ngrok forwards only port 3000; `/health` at the public root is the web
  app's 404, and the backend still refuses any remote write without the secret.
- **Money at risk:** none. Orders go to the simulated account or Webull **paper** (`BROKER` in `.env`); there is no
  live-money broker. With `BROKER=webull` an approved staged order can reach the paper account, so share the
  password only with people you would let click Approve.
- **Not covered:** a leaked password gives full demo control until you stop `make share` (Ctrl-C) or change
  `NGROK_BASIC_AUTH`. Basic auth has no rate limit of ours; rely on a strong password and a short sharing window.
  Secrets (`AGENT_TOOL_SECRET`, `NGROK_BASIC_AUTH`, broker and AI keys) are read from `.env` and never printed.
