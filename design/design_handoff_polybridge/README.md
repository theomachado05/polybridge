# Handoff: PolyBridge — prediction-market → equity hedging app

## Overview
PolyBridge reads prediction-market order books (Polymarket, Kalshi) as a price signal, estimates how a resolving event would move the equities a user holds, composes a hedge from a proprietary library of ~1,284 algorithms, and executes it in the user's brokerage account (Webull primary) — fee- and tax-aware, explaining every fill. This package covers the full product flow: Landing → Build (chat wizard) → Connect brokerage → AI pipeline → Live Bridge (multi-bridge) → Portfolio → Library → Profile.

## About the design files
Files in this bundle are **design references built in HTML** — prototypes showing intended look, motion and behavior, not production code. The task is to **recreate these designs in the target codebase's existing environment** (React/Next, Vue, Swift, etc.) using its established patterns and libraries. If no environment exists yet, pick the most appropriate stack (React + TypeScript recommended; the prototype's logic is a React-style class and ports almost 1:1). The live market data is **simulated** in the prototype — see "State & data" for what to replace with real feeds.

## Fidelity
**High-fidelity.** Colors, type, spacing, radii, shadows and copy are final. Recreate pixel-perfectly, substituting the codebase's own component primitives where equivalent.

## Visual language (read first)
- **Aesthetic**: Apple "liquid glass" panels on warm paper, with america.gov editorial restraint (hairline rules, numbered uppercase mono labels, serif headlines) and an AI-company feel (serif AI voice, a dotted 3D "thinking orb" as the product's character).
- **Background** (fixed, behind everything): paper `#F3F1EB`; three slowly drifting blurred radial blobs (blue `rgba(110,150,255,.42)`, peach `rgba(236,190,150,.34)`, lavender `rgba(168,140,255,.34)`, `filter: blur(28–32px)`, 16–22s ease-in-out loops); **one** 48px square grid of 1px lines `rgba(15,22,38,.09)` masked with `radial-gradient(ellipse at 50% 30%, #000 30%, transparent 78%)`. Grid is a user tweak (`showGrid`).
- **Glass panel** (the one card recipe, used everywhere): `border-radius: 28px; background: rgba(255,255,255,.55); backdrop-filter: blur(28px) saturate(1.6); border: 1px solid rgba(255,255,255,.85); box-shadow: inset 0 1px 0 rgba(255,255,255,.95), 0 20px 50px rgba(40,60,120,.10)`. Inner sub-cards: radius 18px, `rgba(255,255,255,.6)`, border `rgba(255,255,255,.9)`.
- **Pills**: radius 999px. Primary action: `#0F1626` bg, white text, `0 12px 30px rgba(15,22,38,.25)` shadow, height 48–52px, padding 0 22–26px, weight 600, 15px. Secondary: `rgba(255,255,255,.6)` + border `rgba(255,255,255,.9)`.
- **Section labels** (america.gov element): `Geist Mono 11px, letter-spacing .08em, uppercase, color #5A627A`, numbered `01 · PREDICTION MARKET`, `02 · DELTA-BRIDGE V3` … Page headers sit on a hairline `1px solid rgba(15,22,38,.16)`.
- **Thinking orb**: `thinking-orbs.js` (bundled; MIT port of github.com/Jakubantalik/thinking-orbs). Web component `<thinking-orb state size ink>`; states used: `connecting` (network — bridge center), `working` (orbits — impact model / thinking), `searching` (globe), `composing` (ribbon), `breathing` (ring — idle/ready), `listening` (wave). Default bridge orb state is a tweak (`bridgeOrb`).

## Typography
- **Newsreader** (Google; opsz 6–72) — serif: wordmark (19px/500), page H1/H2 (400, letter-spacing −.015 to −.02em), AI chat messages (21px/1.45), big numerals on the bridge (clamp(38px,4vw,56px), 400, −.02em, tabular), net P&L (46px), market question on the bridge (25px).
- **Geist** — UI sans: body 13–15px, labels 11–12px, buttons 15px/600, tickers 15–22px/600 with −.02em.
- **Geist Mono** — numbers in tables, section labels, step eyebrows, hints (11–12.5px).
- Text color `#0F1626`; secondary `#3C4458`; muted `#5A627A`; disabled/placeholder `#8A92A8`. Use `text-wrap: pretty/balance` on headlines and prose.

## Design tokens
Colors: ink `#0F1626` · text-2 `#3C4458` · muted `#5A627A` · faint `#8A92A8` · paper `#F3F1EB` · accent blue `#3B6CF6` (text `#2B57D6`, tint `rgba(59,108,246,.12)`) · lavender `#9A7BFF` · up/green `#22A06B` (text on light `#15804F`, on dark `#7EE0B0`, dot `#4ADE80`) · down/red `#E0485A` (text on light `#C8323F`, on dark `#FF8A96`) · amber `#FBBF24` (pipeline status) · hairline `rgba(15,22,38,.16)`, row divider `rgba(15,22,38,.07)`, bar track `rgba(15,22,38,.08)`.
Radii: 999 pills · 28 panels · 22 option/chat containers · 18–20 rows/sub-cards · 16 compact rows · 10 logo tiles.
Spacing: page gutter 40px; panel padding 22–26px; grid gap 16px; row padding 12–14px 14–18px; nav height 44px.
Motion: `pb-in` fade/slide-up 10px, .3–.5s ease-out on screen/message mount; `pb-pulse` 1.6s on live dots; `pb-ring` 3s expanding ring around the orb; `pb-shimmer` 2.2s linear gradient travelling along bridge connectors; hover on rows → `background: rgba(255,255,255,.9–.95)` .2s; width transitions .6s on bars; all pill state changes .25s.
Layout: fluid, desktop-first; content max-widths 1180 (landing), 780 (chat), 760 (connect), 820 (pipeline), 1400 (bridge/portfolio), 1040 (profile). Grids use `minmax(0,1fr)` and `repeat(auto-fit, minmax(min(100%,420px),1fr))` so panels wrap below ~900px.

## Global chrome
Top nav, 22px 40px padding, three glass pills in a row: left wordmark pill (gradient dot `#3B6CF6→#9A7BFF` 18px + "PolyBridge" serif) → clicks to Landing; center segmented tabs **Build · Bridge · Library · Portfolio** (active tab: white bg + `0 2px 8px rgba(20,30,60,.12)`); right: dark status pill (`rgba(15,22,38,.9)`, pulsing dot: green when live, amber during pipeline, lavender otherwise; label e.g. "Live · 3 bridges", "Composing bridge", "Step 2 of 3", "1,284 algorithms", "2 connections", "Paper trading") + 44px circular avatar "JD" → Profile (inverts to dark when on Profile).

## Screens

### 1. Landing
Centered column. Glass eyebrow pill (orb 20px + Polymarket/Kalshi marks + "Prediction markets → your portfolio", blue text). H1 serif clamp(44px,6vw,80px): **"Hedge the headline before it hits your stock."** Paragraph 18px `#3C4458` max 640px. Two buttons: primary **Build a bridge →** (→ Build) and secondary **Watch a live bridge** (seeds 3 demo bridges and opens Bridge). Below (70px): three glass cards, auto-fit ≥280px, each with hairline-topped blue mono eyebrow (`01 · REVERSE THE BRIDGE`, `02 · AI-COMPOSED ALGOS`, `03 · YOUR FEES, YOUR TAXES`), serif 25px title, 14px body. Copy is in the HTML.

### 2. Build — chat wizard (the core UX)
Max-width 780. Top: ruled 3-column strip `01 · EVENT / 02 · EQUITY / 03 · HEDGE` (mono 10.5px; active label blue `#2B57D6`, filled ink, pending `#8A92A8`; value line 13px ellipsized: event phrase / "TICKER · Name" / instrument short name; "Choosing…" or "—" when empty). Clicking a column re-opens that step (clears it and everything after).
Thread (24px gap):
- **AI message**: 36px glass circular avatar with orb (26px) + serif 21px text. Opening: "What are you worried about? I'm watching 1,284 markets on Polymarket and Kalshi — pick one below, or describe it."
- **Options container** under the active AI message: glass radius 22, padding 6; rows radius 16, 12px 14px, hover white .95. Step 1 rows: question (14.5px/500) + sub "Polymarket + Kalshi · moves ABNB, EXPE, MAR · you hold ABNB" (12px muted); right: YES price (17px/600 tabular) + "YES · 48.2k vol". Shows 5 held-first; footer mono hint "3 more markets — type to search". Step 2 rows: ticker (15/600) + name + green "1,200 sh held"; second line the model's one-sentence reason; right: expected move colored red/green + "on YES". Step 3 rows: instrument name + blue "AI pick" tag; line 2 "fit · tax"; right: cost + coverage.
- **User message**: right-aligned dark bubble `#0F1626`, radius `22 22 6 22`, 15px, max 78%, clickable to edit (reverts to that step). Copy: "If California bans short-term rentals before 2027." / "Protect ABNB." / "With a dynamic short hedge."
- **Thinking state** (900ms after any pick): avatar with `working` orb + italic serif 19px muted text ("Reading the order books…", "Mapping exposure across 23 equities…", "Pricing hedges for your Taxable account…", "Checking fees and lot ages…"). The next AI message and its options appear when it clears. Page smooth-scrolls to bottom on each change (`window.scrollTo`).
- AI replies are templated from data: step 2 "That market is at 23¢ YES on Polymarket and Kalshi, with 48.2k traded in the last 24 hours. It moves ABNB most — −3.2% if YES resolves, and you hold ABNB. Which position should I protect?"; step 3 "You hold 1,200 shares of ABNB across three lots, two of them long-term. Delta-Bridge expects −3.2% on YES: {reason} How should I hedge it?"; final "{instrument fit} Next I'll connect your brokerage, then compose the chain from 1,284 algorithms and tune it to your fees and 32% tax rate." + buttons **Connect brokerage →** / Start over.
- **Composer**: sticky bottom 24px, 60px glass pill (`rgba(255,255,255,.74)`), input 16px with contextual placeholder ("Describe an event — e.g. Fed cuts in December" / "Or type any ticker" / "Or describe the hedge you want" / "Anything to adjust before I connect?"), mono hint "↵ picks the top match", 44px dark circular ↑ button. Typing filters the current step's options (questions by text/phrase/ticker; equities across the whole universe; instruments by name/kind). Enter picks the top match; after the hedge is chosen, Enter continues to Connect.

### 3. Connect brokerage
Max 760, one glass panel. Eyebrow `ONE LAST THING` (hairline above), serif H2 "Where does ABNB live?", 14px explainer. Grid of broker cards (auto-fit ≥150px): white 34px logo tile (favicon via `https://www.google.com/s2/favicons?domain=…&sz=128`, 22px, contain) + name 14/600 + sub 11.5. Webull first and pre-connected ("$0 commission · primary"); then Alpaca, Interactive Brokers, Schwab, Robinhood. Selected card: white bg + border `rgba(59,108,246,.6)`. Status row (glass 18px): orb `breathing` when connected / `searching` when not + text "Connected · ABNB: 1,200 sh in 3 lots (2 long-term) · commission $0 · borrow 0.3%". Two chip groups: Account type (Taxable / IRA), Marginal tax rate (24/32/35/37%) — selected chip dark. Footer: "← Back to the bridge" and primary **Run the AI pipeline →** (disabled grey `rgba(15,22,38,.08)`/`#8A92A8` until a broker is chosen).

### 4. AI pipeline
Centered. 220px glass disc with expanding `pb-ring` and a 170px orb whose state follows the step. Mono eyebrow `STEP n OF 6` → `BRIDGE READY`; serif H2 "{step name}…" → "ABNB is bridged to the market". Glass list of 6 steps, each row: 22px numbered dot (grey → dark when active → green ✓ when done), name 14/600, streamed text 13px with a blinking 7×14 blue caret on the active row. Steps advance every 1.4s: Parsing question (`searching`) → Mapping exposure (`connecting`) → Estimating impact (`working`) → Searching algo library (`searching`) → Composing the chain (`composing`) → Backtesting on comps (`listening`). Texts are in the HTML (`PIPE`). Button below: secondary "Skip to the bridge →" becomes primary "Open the live bridge →" when done; auto-opens the bridge 1.4s after completion.

### 5. Bridge (live)
Max 1400, 16px column gap.
- **Bridge strip** (ruled bottom): mono "3 BRIDGES · +$1,240 TODAY" (P&L colored), one pill per bridge (46px; dot — green when it fired in the last 2 ticks; ticker 13/600; event phrase ellipsized ≤240px at .72 opacity; mono P&L). Active pill is dark with light-green/pink P&L. "+ New bridge" dashed pill → Build.
- **Top row** grid `minmax(0,1fr) clamp(20px,5vw,72px) minmax(170px,240px) clamp(20px,5vw,72px) minmax(0,1fr)`: Market panel (`01 · PREDICTION MARKET` + venue pills with marks; question in serif 25px; YES price serif big + "Kalshi 24¢ · confirming/diverging from Polymarket"; 150×56 blue sparkline `#3B6CF6` 2px of the last 60 probabilities; footer "24h volume"). Connector: 2px line with travelling shimmer (blue left, red right). Center: 170px glass disc + ring + orb (`connecting`), label `02 · DELTA-BRIDGE V3`, "Rev −1.0% · Brand −5.0% / Expected move on YES −3.2%" (red). Equity panel (`03 · EQUITY · NASDAQ` + instrument pill; ticker + name; price serif big + change colored; ink sparkline of the last 60 prices; footer "Priced-in drift from market").
- **Algo dock**: one glass pill row, label `04 · 6 OF 1,284 ALGOS`, six capsules (flex 1, min 170px): name 12.5/600 + status right (Watching/Reading/Armed → Passed/Fired/Executing in green when firing) and "σ 31% · 64 sh · 38 ms" line; active capsules `rgba(255,255,255,.85)` with blue border, idle `.35`. Chain: Sigma Gate → Book-Imbalance Reader → Delta-Bridge v3 → Vol-Adaptive Slicer *or* Meridian TWAP (urgent vs calm) → Tax-Lot Optimizer → Fee-Aware Router.
- **Bottom row** (auto-fit ≥340px): Portfolio panel (`05 · PORTFOLIO`: net P&L serif 46px colored; two sub-cards Long / Hedge short; "Event exposure covered" gradient bar `#3B6CF6→#9A7BFF`; footer "Fees $4.12 · 9 fills" / "ST gains avoided · est. $479 saved" or "IRA · no tax drag"). Trades panel (`06 · TRADES & REASONING`): newest-first cards with SELL (red) / BUY (green) tag + time, "64 ABNB @ 128.71 · Vol-Adaptive Slicer", and the reasoning sentence (see data section). New cards animate in.

### 6. Portfolio
Header: mono `PORTFOLIO · Webull`, serif total value, "Total equity value · +$1,240 net today across 3 bridges"; right: three stat sub-cards (Event exposure covered %, Fees today, Fills today). Grid auto-fit ≥420px: **01 · HOLDINGS** table (Position / Shares / Price / Value / Today / Bridge; mono numerals right-aligned; Bridge cell = green "Bridged" tag + "event · 38% covered", or dark "Bridge it" tag + "2 markets touch this" → opens Build with the composer pre-filled with the ticker). Right column: **02 · EXPOSURE BY EVENT** (per bridge: ticker · event, P&L, gradient coverage bar, "38% covered"; click → that bridge) and **03 · RECENT FILLS** (merged across bridges, newest 7). Prices are live for bridged holdings, static otherwise.

### 7. Library
Header: `LIBRARY · 1,284 ALGORITHMS`, serif "Composed per event, tuned per tick.", explainer; right: family chips (All, Gate, Reader, Impact, Execution, Tax, Routing). One glass list; row grid `84px minmax(0,1.6fr) minmax(160px,.9fr) 130px`: mono ID (PB-0001…), name 15/600 + family tag, role sentence 12.5px, "Tunes" + mono parameters, status pill "In 3 bridges" (green) / "Available" (grey). 15 sample algorithms are in the HTML (`ALGOS`); the real list is paginated/virtualized.

### 8. Profile
Header `PROFILE · 2 CONNECTIONS` / `PAPER TRADING`, serif "Jordan Dale", subtitle. Four glass panels (auto-fit ≥420px): **01 · BROKERAGES** (logo tile, name, fee note, Connect ↔ Connected toggle button), **02 · PREDICTION MARKETS** (Polymarket "CLOB websocket · read-only", Kalshi "REST · read-only", 44×26 switches; note "Read-only. PolyBridge never trades the contracts — it reads them to trade your equities."), **03 · TAX & ACCOUNT** (Account type, Marginal rate, State: CA/NY/TX/Other chips), **04 · GUARDRAILS** (switches: Act only when edge beats fees + borrow; Respect wash-sale windows; Auto-execute without confirmation; chips Maximum hedge ratio 50/75/100%). Switch: track `#0F1626` on / `rgba(15,22,38,.15)` off, 20px white knob translating 18px.

## State & data
Screen enum: `landing | wizard | connect | pipeline | bridge | portfolio | library | profile`.
Wizard: `qId, eq, inst, query, thinking` (step is derived: no question → 1, no equity → 2, else 3).
Account: `broker, conns[], account (Taxable|IRA), rate, taxState, maxHedge, markets{Polymarket,Kalshi}, guards{edge,wash,auto}`.
Bridges: `bridges[] = { id: qId+':'+eq, qId, eq, inst, sim }`, `activeId`. One interval (`tickMs`, default 900) steps every bridge's sim while on Bridge or Portfolio.
Sim per bridge (replace with real feeds): probability random walk with 8% chance of a 1–4¢ jump; Kalshi = Polymarket + noise; fair price = base × (1 + impact × (p − p0)); price mean-reverts to fair; realized σ and 24h volume drift; a hedge fires when |p − pAtHedge| > 1.1¢ and ≥3 ticks since last fill: qty ≈ shares × |impact| × 100 × |Δp|; SELL when the move hurts the long; algo = Vol-Adaptive Slicer if |Δp| > 2.5¢ or σ > 40%, else Meridian TWAP; fee = 0.0035/sh + $0.20. Reasoning string: "Polymarket YES +1.8¢ on 61.2k volume; Kalshi 25¢ confirming. Delta-Bridge expects ABNB drift −0.06%. Added hedge via Vol-Adaptive Slicer: σ 30%, 3 slices, 41 ms. Fee $0.42, no wash-sale."
Impact model inputs per (question, ticker): expected move %, revenue %, brand/regulatory %, one-sentence reason — see `IMPACTS`. Questions (`QUESTIONS`): text, short phrase (`ev`), venues, YES¢, volume, resolve date, category, tickers touched. Equities (`EQ`): name, price, shares held. Instruments (`INSTRUMENTS`): dynamic short (AI pick), put spread, zero-cost collar, direct YES contract — with coverage, cost, tax note, fit sentence.
Tweaks exposed in the prototype (map to settings/feature flags): `bridgeOrb`, `showGrid`, `startScreen`, `tickMs`.

## Assets
- `thinking-orbs.js` — orb web component (bundled, MIT; original TypeScript source at github.com/Jakubantalik/thinking-orbs). Port to a React component or load as a custom element.
- Brand marks: fetched at runtime via Google favicon service for webull.com, alpaca.markets, interactivebrokers.com, schwab.com, robinhood.com, polymarket.com, kalshi.com. **Replace with licensed SVG logos in production.**
- Fonts: Google Fonts — Newsreader (ital, opsz 6..72, 400/500), Geist (300–700), Geist Mono (400/500).
- No raster imagery; sparklines are inline SVG paths.

## Files
- `PolyBridge.dc.html` — the full prototype (template + logic class + data). Open directly in a browser.
- `thinking-orbs.js` — orb component used by the prototype.
- `support.js` — prototype runtime only (not for production).
- `PolyBridge Directions.dc.html` — the three early visual directions (1a Federal Ledger, 1b Liquid Glass — chosen, 1c Node Canvas). Reference only.
