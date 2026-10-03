# Talk to PolyBridge: ElevenLabs voice agent

The voice agent is an ElevenLabs Conversational AI agent whose tools are PolyBridge's own backend. The browser
widget handles audio; the agent calls `POST /agent/tool/{name}` on your backend and reads the `summary` field aloud.
Nothing is bought or started by voice alone: `approve` and `start_bridge` are refused unless the request carries
`confirm: true`, and the agent is instructed to ask first.

## Environment variables

| Variable | Where | Purpose |
|---|---|---|
| `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` | `web/.env.local` | Agent id from the ElevenLabs dashboard. Unset means no voice button renders and no script loads. |
| `ELEVENLABS_API_KEY` | your shell or `.env` (never commit) | Only needed if you create or edit the agent through the ElevenLabs API or CLI. The web app and backend do not read it. |
| `AGENT_TOOL_SECRET` | backend env (the repo `.env` that `make dev` loads) | **Required for the tunnel.** A random string; every write that reaches the backend from outside localhost must send it as `X-Agent-Secret`, or the backend answers 401. See [Required shared secret](#required-shared-secret). |
| `GEMINI_API_KEY` | backend env | Optional. The `fit` tool uses Gemini to classify and explain when set, and falls back to rules when not. |

## Backend surface

- `GET /agent/tools` returns the tool schemas (name, short voice-friendly description, JSON Schema parameters,
  the underlying `method` and `path`, and the `webhook` the agent should call).
- `POST /agent/tool/{name}` takes the tool arguments as a flat JSON body and returns
  `{ ok, tool, summary, data }`. Failures are `ok: false` with a speakable `summary` (HTTP 200); an unknown tool is 404.
  The dispatcher never answers 500.

| Tool | Underlying route | Needs confirm |
|---|---|---|
| `search_markets` | `GET /markets/search` | no |
| `fit` | `POST /pipeline/fit` | no |
| `propose` | `POST /proposals` | no (does nothing until approved) |
| `approve` | `POST /proposals/{pid}/approve` | **yes** |
| `start_bridge` | `POST /bridges` | **yes** |
| `bridge_status` | `GET /bridges/{id}` | no |
| `account` | `GET /account` | no |
| `positions` | `GET /positions` | no |

## Expose the backend

ElevenLabs servers must reach your backend, so run a tunnel to the local FastAPI port:

```bash
cd backend && uv run --env-file ../.env uvicorn app.main:app --port 8000
ngrok http 8000        # or: cloudflared tunnel --url http://localhost:8000
```

Use the HTTPS URL it prints as `TUNNEL_URL` below. A tunnel exposes the **whole** backend, not just `/agent/*`, while
it is up. Two things limit the damage (details in [Required shared secret](#required-shared-secret)): the backend
refuses every tunnelled write without the secret, but tunnelled **reads** (`GET /account`, `/positions`, `/orders`,
`/bridges/{id}` and so on) are open to anyone who has the URL. So set the secret before you start the tunnel, limit the
tunnel to `/agent/*` if your provider can (the agent only needs `POST /agent/tool/<name>`, plus `GET /agent/tools` for
the one-off schema copy), and close the tunnel after the demo. CORS is not an issue for server tools (ElevenLabs
calls them server to server).

## Create the agent

1. ElevenLabs dashboard, Agents, Create agent, blank template. Name it `PolyBridge`.
2. **First message:** `Hi, I'm PolyBridge. Tell me a stock you hold and an event you worry about, and I'll find a hedge.`
3. **Voice:** pick a calm, clear voice such as "Sarah" or "Charlie" from the library. Set stability around 0.5 and
   keep speed at 1.0 so numbers are easy to follow. Any voice works; clarity beats character here.
4. **LLM:** any fast model (Gemini 2.5 Flash is a good default). Low latency matters more than depth.
5. **System prompt** (paste as is):

```text
You are PolyBridge, a voice assistant that helps a retail investor hedge a stock position using prediction-market
signals. This is a simulated paper-trading account; say so if asked about real money.

Speak in short plain sentences, no markdown, no lists longer than three items. Say prices as percent, money as
whole dollars. Never read ids aloud except a proposal id or bridge id when the user needs it.

Workflow:
1. Learn the ticker, roughly how many shares, and the event the user worries about.
2. Call search_markets, read the top one or two results, and confirm which market they mean.
3. Call fit to choose a hedge. Explain the result in one or two sentences. The score is how much extra risk the
   hedge removed beyond a plain fixed hedge of the same average size, measured on past data, not a forecast. A score
   near zero or below means the market signal added little; say so. Never call it the hedge's edge or promise it
   will repeat. A score of "unscored" means a rules-based pick, not a tested one.
4. Call propose. Read back the ticker, share count, coverage, and the market.
5. ASK: "Shall I approve this?" Only after the user clearly says yes, call approve with confirm true.
6. ASK again before starting the hedge: "Shall I start it on replay?" Only after yes, call start_bridge with
   confirm true. Use source replay unless the user asks for live.
7. Use bridge_status, account, and positions when asked how it is going.

Rules:
- Never set confirm to true on your own. A confirmation must come from the user's last turn.
- If a tool returns ok false, say its summary plainly and offer the next step. Do not retry confirm-gated tools.
- This is not investment advice. Do not promise returns. A hedge reduces a specific risk and costs money.
- If you do not know something, say so.
```

6. **Tools:** add one **Server tool (webhook)** per tool in the table above. For each:
   - URL: `TUNNEL_URL/agent/tool/<name>`, method `POST`, content type `application/json`.
   - Header: **`X-Agent-Secret: <your AGENT_TOOL_SECRET>`, on every tool, with no exception.** A tool without it gets
     401 from the backend and the agent will say the call "did not work".
   - Description: copy it from `GET /agent/tools`.
   - Body parameters: copy the `parameters.properties` from the same response (all are flat JSON fields). Mark
     `required` as listed. For `approve` and `start_bridge`, keep `confirm` required and add to the tool description:
     "Only set confirm true after the user has said yes in their last message."
   - Tip: `curl TUNNEL_URL/agent/tools` prints every schema in one go (a GET, so it needs no secret).
7. Under Security, enable the allowlist for your web origin (for example `http://localhost:3000`) so the widget only
   runs on your site.
8. Copy the agent id into `web/.env.local`:

```bash
echo 'NEXT_PUBLIC_ELEVENLABS_AGENT_ID=agent_xxxxxxxx' >> web/.env.local
cd web && pnpm dev
```

Open the UI at **http://localhost:3000** on the machine that runs the backend, never through the tunnel URL (see
[Required shared secret](#required-shared-secret)). A "Talk to PolyBridge" pill appears bottom right. Click it: the
widget script loads from the ElevenLabs embed on first click and the widget opens. Press the widget's own Start call
button and allow the microphone; then the agent greets you.

## Required shared secret

`AGENT_TOOL_SECRET` is mandatory whenever the tunnel is up. The check lives in `backend/app/security.py` and runs on
every route, not only `/agent/*`:

- A request is **local** when it comes from the loopback interface (127.0.0.1 or ::1), carries a `localhost`,
  `127.0.0.1` or `[::1]` Host header, and has no proxy-forwarding header (`X-Forwarded-For`, `X-Forwarded-Host`,
  `Forwarded`, `X-Real-Ip`, `Cf-Connecting-Ip`, `True-Client-Ip`, `Ngrok-Trace-Id`). A tunnel forwards from 127.0.0.1
  but adds those headers and keeps its public Host, so everything through the tunnel counts as **remote**.
- A remote request that is not `GET`, `HEAD` or `OPTIONS` (`POST /agent/tool/*`, `POST /orders`, `DELETE /orders/{id}`,
  `POST /account/reset`, `POST /proposals/{id}/approve`, `POST /bridges`, ...) must carry `X-Agent-Secret` equal to
  `AGENT_TOOL_SECRET`. With the variable **unset** it gets 401 ("Remote write refused ... Set AGENT_TOOL_SECRET");
  with a missing or wrong header it gets 401 ("Missing or wrong X-Agent-Secret."). The comparison is constant time.
- Remote reads (`GET`) are not blocked. That is why you should also limit the tunnel to `/agent/*`.
- A remote `POST /orders` never chooses its own fill price: the backend drops any `ref_px`, `ref_half_spread` and
  `ref_source` it carries, even with the right secret.
- Local requests are unaffected: the browser UI on localhost and every test client work without the secret. If the
  secret **is** set, `/agent/tool/*` also requires it from local callers.

Setup:

```bash
openssl rand -hex 24                    # copy the output
echo 'AGENT_TOOL_SECRET=<that string>' >> .env      # then restart the backend so it has the variable
```

Then in ElevenLabs add the custom header `X-Agent-Secret: <same string>` to **every** server tool (step 6 above).
Do not paste the secret into the system prompt or the agent's first message.

Recommended hardening:

- **Limit the tunnel to `/agent/*`.** Use your tunnel provider's path or traffic rules so only `/agent/...` reaches
  the backend (for example a Cloudflare Tunnel ingress rule with a `path`, or an ngrok traffic policy; the exact
  syntax is provider-specific and not part of this repo). Then the account, positions and bridge reads are not
  reachable from outside at all.
- **Open the UI on localhost, never on the tunnel URL.** A page opened at `TUNNEL_URL` sends its writes as remote
  requests without the secret, so every approve, start and order from that page returns 401 (and the UI's CORS
  allowlist is `http://localhost:3000` and `http://127.0.0.1:3000` only). Use `http://localhost:3000` on the backend's
  own machine; the tunnel is for ElevenLabs only.
- Rotate the secret after the demo (change the env var and the ElevenLabs header) and close the tunnel.

## Sanity check before the demo

Run these from a shell on any machine, with `SECRET` set to your `AGENT_TOOL_SECRET`:

```bash
curl -s TUNNEL_URL/agent/tools | head -c 300                       # a GET: 200 with no secret
curl -s -X POST TUNNEL_URL/agent/tool/account -H 'content-type: application/json' -d '{}'
                                                                   # no secret: must answer 401 (the guard works)
curl -s -X POST TUNNEL_URL/agent/tool/approve -H 'content-type: application/json' -H "X-Agent-Secret: $SECRET" \
  -d '{"proposal_id":"x"}'                                         # must answer ok:false, needs_confirmation:true
curl -s -X POST TUNNEL_URL/agent/tool/account -H 'content-type: application/json' -H "X-Agent-Secret: $SECRET" -d '{}'
                                                                   # ok:true with the account summary
```

If the second call answers 200, the secret is not set in the backend's environment: stop and fix that before anyone
else has the URL. If the last call answers 401, the header value does not match.

## 60-second spoken demo script

Times are approximate. Lines in quotes are what you say; the agent's reply is paraphrased.

- **0:00** Click the pill, press Start in the widget, allow the mic. Agent greets. *"I hold two hundred shares of Airbnb and I'm nervous about the Fed."*
- **0:10** Agent searches and reads the top market: a Fed rate decision at some percent. *"Yes, that one."*
- **0:20** Agent calls fit and explains the chosen hedge in a sentence, noting if it is rules-based. *"Make a proposal at fifty percent coverage."*
- **0:30** Agent reads back the proposal and asks: "Shall I approve this?" Say *"Yes, approve it."*
- **0:38** Agent approves, then asks whether to start on replay. Say *"Yes, start it on replay."*
- **0:45** Agent starts the bridge and says it is running. Point at the Bridge page, where ticks and decisions stream.
- **0:50** *"How is it doing, and what's in my account?"* Agent reads bridge status, cash, and total value.
- **0:58** Close with: *"That is PolyBridge: a spoken question to a confirmed, fee-aware hedge, and nothing runs without my yes."*

If the agent ever skips the confirmation question, stop and tighten step 5 and 6 of the system prompt; the backend
will refuse anyway, which is also a good thing to show.
