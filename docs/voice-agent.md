# Talk to PolyBridge: ElevenLabs voice agent

The voice agent is an ElevenLabs Conversational AI agent whose tools are PolyBridge's own backend, called from the
browser. It uses **client tools**: when the agent decides to call a tool, the ElevenLabs widget on
`http://localhost:3000` receives the call, the page sends `POST /agent/tool/{name}` to the backend on
`localhost:8000`, and hands the response's `summary` back to the agent, which reads it aloud. ElevenLabs never reaches
the backend, so **no tunnel** is needed and nothing on the backend is exposed.

Nothing is bought or started by voice alone: `approve` and `start_bridge` are refused unless the call carries
`confirm: true`, and the agent is instructed to set it only after the user said yes.

```
you (mic) -> ElevenLabs agent (cloud: speech, LLM) -> client tool call -> widget in your browser
          -> POST localhost:8000/agent/tool/<name> -> {ok, summary, data} -> widget -> agent speaks the summary
```

## Setup in three commands

Keys go in the repo-root `.env` (gitignored; never commit them, never paste them in chat or code):
`GEMINI_API_KEY=...` and `ELEVENLABS_API_KEY=...`.

```bash
make keys-check      # which keys are present (names only); runs the Gemini check and read-only ElevenLabs calls
make voice-agent     # creates (or updates) the agent and its 8 client tools; writes web/.env.local
make dev             # restart so Next.js picks up NEXT_PUBLIC_ELEVENLABS_AGENT_ID; open http://localhost:3000
```

`make voice-agent ARGS=--dry-run` prints the exact tools and agent body without a key or any network call.

### What `make voice-agent` does (`backend/scripts/elevenlabs_agent.py`, logic in `backend/app/agent/elevenlabs.py`)

1. Reads `ELEVENLABS_API_KEY` (exit 2 with a clear message if missing) and refuses to continue unless git ignores
   `web/.env.local` (exit 3).
2. Creates one **client** workspace tool per entry of `GET /agent/tools` (`POST /v1/convai/tools`), or updates it in
   place when it already exists (`PATCH /v1/convai/tools/{id}`; ours are recognised by name, type `client` and the
   `PolyBridge:` description prefix). Each tool waits for the page's answer (`expects_response: true`); timeouts:
   `fit` 90 s (it replays history), `start_bridge` 30 s, the rest 15 to 20 s. Parameters are the same JSON Schema as
   `GET /agent/tools`; `approve` and `start_bridge` keep `confirm` required and their descriptions say to set it only
   after a spoken yes.
3. Creates the agent (`POST /v1/convai/agents/create`), or updates it (`PATCH /v1/convai/agents/{id}`) when an id is
   known (`ELEVENLABS_AGENT_ID`, else `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` from the environment or `web/.env.local`; a
   stale id that 404s gets a new agent, with a note). The agent gets the system prompt and first message below (read
   from this file, so the doc and the agent never drift), the tools by id (`prompt.tool_ids`; inline `tools` is
   deprecated), LLM `gemini-2.5-flash` (`ELEVENLABS_LLM` to change; if ElevenLabs rejects the name the platform
   default is used and the script says so), the platform default voice unless `ELEVENLABS_VOICE_ID` is set, and a
   widget allowlist of `localhost:3000` and `127.0.0.1:3000` with authentication off (the embed widget needs a
   public agent).
4. Writes **only** `NEXT_PUBLIC_ELEVENLABS_AGENT_ID=<id>` into `web/.env.local` (other lines kept) and prints the id
   masked. The API key is never written anywhere.

Running it again updates the same tools and agent, so edit the prompt below and rerun.

## Environment variables

| Variable | Where | Purpose |
|---|---|---|
| `ELEVENLABS_API_KEY` | repo-root `.env` | Used only by `make voice-agent` and `make keys-check`. The web app and backend never read it. |
| `GEMINI_API_KEY` | repo-root `.env` | The `fit` tool (and `/pipeline/fit`, `/map`) use Gemini when set; keyword rules otherwise, labelled. `make gemini-check` verifies it. |
| `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` | `web/.env.local` (written by `make voice-agent`) | Agent id (not a secret). Unset: no voice button renders and no script loads. |
| `AGENT_TOOL_SECRET` | repo-root `.env` | Required for any call to `/agent/tool/*` from outside the web page on localhost (curl, a tunnel). The page itself needs none (below). |
| `ELEVENLABS_AGENT_ID`, `ELEVENLABS_LLM`, `ELEVENLABS_VOICE_ID` | shell, optional | Update a specific agent; pick the agent's LLM or voice. |

## Backend surface

- `GET /agent/tools` returns the tool schemas (name, voice-friendly description, JSON Schema parameters, the
  underlying `method` and `path`). `make voice-agent` turns exactly these into client tools.
- `POST /agent/tool/{name}` takes the tool arguments as a flat JSON body and returns `{ ok, tool, summary, data }`.
  Failures are `ok: false` with a speakable `summary` (HTTP 200); an unknown tool is 404. Never a 500.

| Tool | Underlying route | Needs confirm |
|---|---|---|
| `search_markets` | `GET /markets/search` (plus matching recorded markets, labelled, e.g. the demo weekend) | no |
| `fit` | `POST /pipeline/fit` | no |
| `propose` | `POST /proposals` | no (does nothing until approved) |
| `approve` | `POST /proposals/{pid}/approve` | **yes** |
| `start_bridge` | `POST /bridges` | **yes** |
| `bridge_status` | `GET /bridges/{id}` | no |
| `account` | `GET /account` | no |
| `positions` | `GET /positions` | no |

`search_markets` appends recorded markets whose question contains every query word (from the replay index), because
a live search does not list resolved markets; the summary names them as "Recorded replays ... (id ...)".

## The web page's side of the contract

The agent only calls client tools the page registers, one handler per tool name, each posting the agent's arguments
unchanged (confirm included) to `POST /agent/tool/{name}` and returning a string for the agent to read. In this repo
`web/src/lib/voice.ts` (`buildClientTools`, used by `web/src/components/voice/VoiceAgent.tsx` through the ElevenLabs
React SDK's `clientTools`) does this. With the plain embed widget the equivalent is:

```ts
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOOLS = ["search_markets", "fit", "propose", "approve", "start_bridge", "bridge_status", "account", "positions"];

widget.addEventListener("elevenlabs-convai:call", (event: any) => {
  event.detail.config.clientTools = Object.fromEntries(TOOLS.map((name) => [name, async (params: object) => {
    const r = await fetch(`${API}/agent/tool/${name}`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(params ?? {}),
    });
    const j = await r.json().catch(() => ({}));
    return j.summary ?? `The ${name} tool did not answer (HTTP ${r.status}).`;   // the agent speaks this string
  }]));
});
```

The browser sends `Origin: http://localhost:3000`; the backend accepts `/agent/tool/*` without the secret only for
a local request with that origin (`app.security.is_local_web_app`). CORS stops any other site's JSON POST from being
sent, and a tunnelled request (proxy headers, public Host) still needs `X-Agent-Secret`. `confirm` is still enforced
by the backend whoever calls.

## Security model

- **No tunnel.** The backend stays on localhost. `app/security.py` still refuses every remote write without
  `X-Agent-Secret` (constant-time compare), and a remote `POST /orders` never chooses its own fill price.
- **`/agent/tool/*` with `AGENT_TOOL_SECRET` set:** a local request (loopback client, localhost Host, no proxy
  header) that carries the web app's `Origin` (`http://localhost:3000` or `http://127.0.0.1:3000`) needs no secret;
  that is how the page's client tools get through, since a browser page cannot hold a secret. Any other caller needs
  `X-Agent-Secret`. A local process can set that `Origin` header itself (the sanity check below does), but a local
  process can already call every other write route without a secret, so this exemption adds no new access. **The
  secret only protects tunnelled and remote callers**; it is not a guard against other software on this machine.
  With the secret unset, local callers are open and remote ones are refused.
- **The agent cannot act alone.** `approve` and `start_bridge` need `confirm: true` (strictly the boolean). The
  prompt tells the agent to set it only after a spoken yes; the backend refuses without it either way.
- **Evidence gate.** On an unvalidated market, `approve` also needs `ack_unvalidated: true`, which the prompt allows
  only after the user acknowledged that the market's signal has not passed its out-of-sample test. The demo weekend
  (US recession 2025 on SPY) is validated and approves without it.
- Open the UI at `http://localhost:3000` (the allowlisted host); the widget does not start elsewhere.

## Agent configuration (read by `make voice-agent`)

First message:

<!-- agent-first-message:start -->
```text
Hi, I'm PolyBridge. Tell me a stock you hold and an event you worry about, and I'll find a hedge.
```
<!-- agent-first-message:end -->

System prompt:

<!-- agent-system-prompt:start -->
```text
You are PolyBridge, a voice assistant that helps a retail investor hedge a stock position using prediction-market
signals. Orders go to a paper or simulated account, never real money; say so if asked.

Speak in short plain sentences, no markdown, no lists longer than three items. Say prices as percent, money as
whole dollars. Never read ids aloud except a proposal id or bridge id when the user needs it.

Workflow:
1. Learn the ticker, roughly how many shares, and the event the user worries about.
2. Call search_markets. Read the top one or two results and confirm which market they mean. Results named as
   recorded replays are past markets that replay recorded prices; say "recorded" when you offer one. For a replay
   demo, prefer the recorded market the user's topic matches.
3. Call fit to choose a hedge (say "one moment" first; it replays history). Explain the result in one or two
   sentences. The score is how much extra risk the hedge removed beyond a plain fixed hedge of the same average
   size, measured on past data, not a forecast. A score near zero or below means the market signal added little;
   say so. Never call it the hedge's edge or promise it will repeat. "Unscored" means a rules-based pick, not a
   tested one. If the result says Gemini was not used, do not claim it was.
4. Call propose with the same ticker, market and direction. Read back the ticker, share count, coverage and market,
   and whether the market's signal is validated or an unvalidated estimate.
5. ASK: "Shall I approve this?" Only after the user clearly says yes, call approve with confirm true. If the market
   is unvalidated, first say that its signal has not passed its out-of-sample test and ask if they accept that; only
   after a yes to that, set ack_unvalidated true.
6. ASK again before starting the hedge: "Shall I start it on replay?" Only after yes, call start_bridge with
   confirm true. Use source replay unless the user asks for live.
7. Use bridge_status, account and positions when asked how it is going.

Rules:
- Never set confirm or ack_unvalidated to true on your own. A confirmation must come from the user's last turn.
- If a tool returns ok false, say its summary plainly and offer the next step. Do not retry confirm-gated tools.
- This is not investment advice. Do not promise returns. A hedge reduces a specific risk and costs money.
- If you do not know something, say so.
```
<!-- agent-system-prompt:end -->

## Sanity check before the demo

```bash
make keys-check                                   # Gemini live? ElevenLabs key accepted? agent exists, 8 tools?
curl -s localhost:8000/agent/tools | head -c 300  # backend up (make dev)
curl -s -X POST localhost:8000/agent/tool/approve -H 'content-type: application/json' \
  -H 'Origin: http://localhost:3000' -d '{"proposal_id":"x"}'
                                                  # ok:false, needs_confirmation:true (the confirm gate works)
curl -s -X POST localhost:8000/agent/tool/account -H 'content-type: application/json' -d '{}'
                                                  # 401 when AGENT_TOOL_SECRET is set: no web-app Origin, no exemption
curl -s -X POST localhost:8000/agent/tool/account -H 'content-type: application/json' \
  -H 'Origin: http://localhost:3000' -d '{}'      # ok:true with the account summary
```

Then on `http://localhost:3000` click **Talk to PolyBridge**, press the widget's Start call button and allow the
microphone.

## 60-second spoken demo (on `make dev`: the validated recession weekend, SPY)

`make dev` replays "US recession in 2025?" over the April 2025 tariff weekend (Friday 15:30 ET to Monday 10:00 ET,
hedging SPY, the one market whose expected gap is validated out of sample). Times are approximate; lines in quotes
are what you say, the agent's replies are paraphrased.

- **0:00** Click the pill, press Start, allow the mic. Agent greets. *"I hold a thousand shares of SPY and I'm
  worried about a recession."*
- **0:08** Agent searches and reads the top live market, then the recorded replay "US recession in 2025?".
  *"Use the recorded 2025 one."*
- **0:16** Agent says "one moment", calls fit and explains the chosen hedge in a sentence (Gemini-written when the
  key is set; it says when the pick is rules-based). *"Make a proposal at fifty percent coverage."*
- **0:28** Agent reads back SPY, 1,000 shares, 50 percent, the market, and that its signal is validated, then asks
  "Shall I approve this?" Say *"Yes, approve it."*
- **0:36** Agent approves, then asks whether to start on replay. Say *"Yes, start it on replay."*
- **0:42** Agent starts the bridge. Point at the Bridge page: the weekend replays, the closed-market panel shows the
  expected gap and the staged order for Monday's open.
- **0:50** *"How is it doing, and what's in my account?"* Agent reads bridge status, cash and total value.
- **0:58** Close with: *"A spoken question to a confirmed, evidence-gated hedge, and nothing runs without my yes."*

If the agent ever skips a confirmation question, tighten steps 5 and 6 of the prompt and rerun `make voice-agent`;
the backend refuses anyway, which is also worth showing.

## Without client tools (not recommended)

The older setup used ElevenLabs **server tools** (webhooks) that call the backend over a public tunnel
(`ngrok http 8000`) with `X-Agent-Secret: <AGENT_TOOL_SECRET>` on every tool. It still works (the backend's remote
write guard is unchanged), but it exposes every backend read to anyone with the URL while the tunnel is up, so the
client-tools flow above replaces it.
