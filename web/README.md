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
ElevenLabs widget renders only when it is set).

## Screens

| Route | Screen | Data |
|---|---|---|
| `/` | Landing | library preset count when `GET /library` works |
| `/build` | Chat wizard (event → equity → hedge) | `GET /markets/search`, `GET /portfolio` markets, `POST /map`, `GET /equities/{t}`, `POST /pipeline/fit` (AI fit card) |
| `/connect` | Connect brokerage | `GET /account` (sim vs Webull paper) |
| `/pipeline` | AI pipeline, 6 steps | `POST /pipeline/fit` → classify, shortlist, history, tune, explain, ready |
| `/bridge`, `/bridge/{id}` | Live bridge (multi-bridge strip) | proposal → approve → `POST /bridges` (replay, then live), `GET /bridges/{id}` + SSE stream |
| `/portfolio` | Holdings, exposure, fills | `GET /portfolio`, `GET /account`, `/positions`, `/orders` |
| `/library` | Algo families and presets | `GET /library` (hedgecore catalog) |
| `/profile` | Connections, tax, guardrails | `GET /account` |

When an endpoint fails or is absent, the screen falls back to the prototype's sample data and says so with a
small label (`demo data`, `sample`, `simulated`). Other labels stay honest: `replay` vs `live`, `simulated` vs
`Webull paper`, `AI estimate` vs `benchmark`. `/bridge?demo=1` seeds the three demo bridges for stage demos.

## Approval and what a live bridge runs

- Nothing trades without an explicit click. The pipeline ends on "Approve and open the bridge"; only then is a
  proposal approved and `POST /bridges` called. With Profile → "Auto-approve bridges" on, the pipeline opens the
  bridge by itself, except when the bridge would start with its fee gate off and the edge guardrail is on.
- A proposal for the same ticker, market and direction is reused (approved → re-attach, pending → approve), so
  repeated runs do not pile up proposals, and an approval left behind by a failed start is picked up next time.
- `POST /bridges` takes no family or preset yet, so live bridges are labelled "engine · default delta-bridge spec";
  the AI fit is shown beside it as "AI fit: … (not applied yet)". When the bridge starts with `gap_per_share = 0`
  (no quote or impact estimate) it shows "fee gate off".
- On live markets the hedge menu offers only the engine's short-shares hedge; option and contract hedges stay on
  sample markets (simulator). Demo bridges never touch real portfolio rows or totals.
- Live trade cards show the broker's fill (`fill` SSE event, v4/broker) when present, else the last quote, labelled.

Code map: `src/lib/store.tsx` (flow state), `src/lib/realBridge.ts` (proposal → approval → bridge, tested),
`src/lib/bridgeStream.ts` (SSE reducer, tested), `src/lib/demo.ts` (prototype data),
`src/lib/sim.ts` (prototype simulator, demo bridges only), `src/lib/library.ts` (catalog → rows; block kinds →
Gate/Reader/Impact/Execution/Tax/Routing), `src/lib/pipeline.ts` (fit → steps), `src/components/pb.tsx`
(design primitives), `public/thinking-orbs.js` (MIT orb web component from the handoff).
