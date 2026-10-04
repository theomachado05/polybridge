# PolyBridge web

Next.js 16 (App Router) + Tailwind 4. The UI recreates the high-fidelity design in
`design/design_handoff_polybridge/` (liquid glass, Newsreader / Geist / Geist Mono, the thinking orb).

```bash
pnpm install
pnpm dev          # http://localhost:3000 (the backend's CORS allows this origin)
pnpm lint
pnpm test         # offline unit tests (node:test, HTTP mocked)
pnpm build
```

Env: `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`), `NEXT_PUBLIC_ELEVENLABS_AGENT_ID` (optional; the
voice button renders, and the ElevenLabs SDK loads, only when it is set).

## Screens

| Route | Screen | Data |
|---|---|---|
| `/` | Landing | library preset count (`GET /library`); "Watch the weekend replay" opens Build preselected on the recorded recession-market weekend |
| `/build` | Chat wizard (event → equity → hedge) | `GET /markets/search`, `GET /portfolio` markets, `POST /map`, `GET /equities/{t}`, `POST /pipeline/fit` (AI fit card) |
| `/connect` | Connect brokerage | `GET /account` (sim vs Webull paper) |
| `/pipeline` | Fit pipeline, 6 steps | `POST /pipeline/fit` → classify, shortlist, history, tune, explain, ready |
| `/bridge`, `/bridge/{id}` | Live bridge (multi-bridge strip) | proposal → approve → `POST /bridges` (replay, then live), `GET /bridges/{id}` + SSE stream |
| `/portfolio` | Holdings, exposure, fills | `GET /portfolio`, `GET /account`, `/positions`, `/orders` |
| `/library` | Algo families and presets | `GET /library` (hedgecore catalog) |
| `/profile` | Connections, tax, guardrails | `GET /account` |

Everything on screen comes from the backend. When an endpoint fails the screen says what is missing, gives the
backend's reason and a Retry (`Unavailable` in `src/components/pb.tsx`); it never shows sample or simulated numbers in
its place. There is no prototype simulator and no demo bridge: every bridge is a backend bridge (a recorded replay or
the live feed). Labels stay honest: `replay` vs `live`, `simulated` vs `Webull paper`, `estimate` vs `benchmark`.

**AI labels** (`src/lib/ai.ts`). "AI · Gemini <model>" appears only when the backend says an LLM answered: the fit's
`llm` names Gemini (`gemini:<model>`) or its `ai.live` is true. Otherwise the label is "Rules + C++ replay", with no
"AI" wording (Build fit card, Pipeline steps and tags, Library badge, Landing card, Connect button). Mappings show
"AI estimate (precomputed)" or "AI (Gemini, live)" from `POST /map`'s `source` (`ai_precomputed` / `ai_live:gemini:…`).
The fitted family and preset are always described as picked by the C++ replay, never by the LLM.

**Weekend replay.** "Watch the weekend replay" (Landing, the empty Bridge screen, and a row on Build step 1) selects
"US recession in 2025?" (Polymarket 516710) → SPY, down on YES, sized from GET /portfolio (500-share notional when not
held). Identity and orientation come from the recording's sidecar
(`backend/replays/us-recession-in-2025-weekend-2025-04-04.jsonl.meta.json`); the market's own search row is used
when the backend returns it. From there it is the normal flow: fit, Connect, Pipeline approval, then a real backend
bridge that replays the recorded weekend.

**Direction.** A ticker outside the market's mapping has no known adverse outcome; Build asks "YES hurts X / NO hurts
X" and orients the hedge to the answer (labelled as the user's), instead of guessing.

## Approval and what a live bridge runs

- Nothing trades without an explicit click. The pipeline ends on "Approve and open the bridge"; only then is a
  proposal approved and `POST /bridges` called. With Profile → "Auto-approve bridges" on, the pipeline opens the
  bridge by itself, except when the bridge would start with its fee gate off and the edge guardrail is on.
- A proposal for the same ticker, market and direction is reused (approved → re-attach, pending → approve), so
  repeated runs do not pile up proposals, and an approval left behind by a failed start is picked up next time.
- `POST /bridges` takes no family or preset yet, so live bridges are labelled "engine · default delta-bridge spec";
  the AI fit is shown beside it as "AI fit: … (not applied yet)". When the bridge starts with `gap_per_share = 0`
  (no quote or impact estimate) it shows "fee gate off".
- The hedge menu offers only the engine's short-shares hedge; option structures are priced from real quotes for
  comparison (`GET /options/hedge-quote`).
- Live trade cards show the broker's fill (`fill` SSE event, v4/broker) when present, else the last quote, labelled.

## Risk controls in the UI (evidence gate, liquidity, capital, Webull, options)

- **Evidence gate.** The Pipeline approval step (and the Opportunity card on Build) first creates the proposal *pending*
  and reads its `evidence` and `capacity`. On an unvalidated market Approve stays disabled until the user ticks the
  acknowledgement; the approval then sends `{ack_unvalidated: true}`. Auto-approve never covers an unvalidated market.
  A 409 `EVIDENCE_UNVALIDATED` is shown, never hidden behind a simulator bridge. Weekend mode on Build has the
  closed-market override (`act_on_unvalidated`). Every decision, fill and staged plan shows its evidence label;
  an `EVIDENCE_GATE` refusal shows on the Bridge's closed-market panel.
- **Liquidity & capacity card** (approval step, Build preview via `GET /liquidity/{t}`, Bridge panel 08): max order,
  max position per day, estimated cost in bp, book-size capacity, binding limit, sources and staleness, plus the
  capital-budget fit. Trade cards badge `liquidity capped` / `capital budget` orders and say why.
- **Portfolio:** 05 the broker account (Webull paper balances, positions, 7-day order history with origin and the
  broker's status word, reconciler status), kept apart from 01 demo holdings; 06 capital usage (`GET /capital`):
  equity, buying power, gross hedge notional, margin, per-event budgets, breaches. The nav shows the account pill
  ("Webull paper · Individual Margin · market closed").
- **Options:** Build shows the hedge-instrument comparison (`GET /options/hedge-quote`: short stock, protective put,
  collar, put spread in $ and bp with liquidity flags) and the strike ladder on demand (`GET /options/chain/{t}`).
  Option legs on opportunity bridges and broker option positions carry marks (`GET /options/mark/{contract}`).
- View logic is pure and tested: `src/lib/risk.ts`, `src/lib/optionsView.ts` (`tests/risk.test.ts`,
  `tests/options_view.test.ts`).

## Voice (ElevenLabs React SDK)

`src/components/voice/VoiceButton.tsx` renders nothing without `NEXT_PUBLIC_ELEVENLABS_AGENT_ID`; with it, it loads
`VoiceAgent.tsx` in the browser only (`@elevenlabs/react`: `ConversationProvider` + `useConversation`). Clicking the
pill asks for the microphone first (a refusal gets a plain message), then starts the session. The orb follows the SDK:
listening (wave), thinking while one of our tools runs (orbits), speaking (ribbon). The agent's **client tools**
(`src/lib/voice.ts`, one per `GET /agent/tools` entry) POST the agent's arguments unchanged to the backend's
`POST /agent/tool/{name}`; the browser never holds `X-Agent-Secret`: the backend accepts these calls without it only
from the web page on localhost (local request, `Origin` in `app.security.WEB_ORIGINS`). `approve` and `start_bridge`
still need the agent's `confirm: true`, which its prompt sets only after the user says yes; the backend refuses
without it. A started bridge opens on screen. Agent setup: `docs/voice-agent.md` (`make voice-agent`).

Code map: `src/lib/store.tsx` (flow state), `src/lib/realBridge.ts` (proposal → approval → bridge, tested),
`src/lib/bridgeStream.ts` (SSE reducer, tested), `src/lib/markets.ts` (questions, picks, the weekend preset),
`src/lib/ai.ts` (AI labels from backend fields), `src/lib/voice.ts` (voice client tools and orb states),
`src/lib/brokers.ts` (brokerage logos), `src/lib/library.ts` (catalog → rows; block kinds →
Gate/Reader/Impact/Execution/Tax/Routing), `src/lib/pipeline.ts` (fit → steps), `src/components/pb.tsx`
(design primitives), `public/thinking-orbs.js` (MIT orb web component from the handoff). `tests/honest.test.ts` pins
the rules above (no demo/sim code, labels from backend fields, voice hidden without an agent id).
