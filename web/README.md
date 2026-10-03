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

Code map: `src/lib/store.tsx` (flow state, real-bridge start), `src/lib/demo.ts` (prototype data),
`src/lib/sim.ts` (prototype simulator, demo bridges only), `src/lib/library.ts` (catalog → rows; block kinds →
Gate/Reader/Impact/Execution/Tax/Routing), `src/lib/pipeline.ts` (fit → steps), `src/components/pb.tsx`
(design primitives), `public/thinking-orbs.js` (MIT orb web component from the handoff).
