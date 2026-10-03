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

Use the HTTPS URL it prints as `TUNNEL_URL` below. The tunnel makes the paper-trading API public while it is up,
so close it after the demo. CORS is not an issue for server tools (ElevenLabs calls them server to server).

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
3. Call fit to choose a hedge. Explain the result in one or two sentences, including that a score of "unscored" means
   a rules-based pick, not a tested one.
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
   - Description: copy it from `GET /agent/tools`.
   - Body parameters: copy the `parameters.properties` from the same response (all are flat JSON fields). Mark
     `required` as listed. For `approve` and `start_bridge`, keep `confirm` required and add to the tool description:
     "Only set confirm true after the user has said yes in their last message."
   - Tip: `curl TUNNEL_URL/agent/tools` prints every schema in one go.
7. Under Security, enable the allowlist for your web origin (for example `http://localhost:3000`) so the widget only
   runs on your site.
8. Copy the agent id into `web/.env.local`:

```bash
echo 'NEXT_PUBLIC_ELEVENLABS_AGENT_ID=agent_xxxxxxxx' >> web/.env.local
cd web && pnpm dev
```

A "Talk to PolyBridge" pill appears bottom right. Click it: the widget script loads from the ElevenLabs embed on
first click and the widget opens. Press the widget's own Start call button and allow the microphone; then the agent greets you.

## Optional shared secret

The tunnel URL is public. Set `AGENT_TOOL_SECRET=<random string>` in the backend env, and add a custom header
`X-Agent-Secret: <same string>` on each ElevenLabs server tool. With the variable unset, `/agent/tool/*` stays open.

## Sanity check before the demo

```bash
curl -s TUNNEL_URL/agent/tools | head -c 300
curl -s -X POST TUNNEL_URL/agent/tool/approve -H 'content-type: application/json' \
  -d '{"proposal_id":"x"}'          # must answer ok:false, needs_confirmation:true
curl -s -X POST TUNNEL_URL/agent/tool/account -H 'content-type: application/json' -d '{}'
```

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
