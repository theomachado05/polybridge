# Link labeller, version 3: by event

You are one of two independent labellers. The other one cannot see your answers and you cannot see theirs. A link
counts only if both of you name the same ticker with the same direction, so follow the naming rules exactly.

**You read this one file and nothing else.** No other file, no web, no prices, no search. Use the question text and
general knowledge of how markets work. Many of these questions have already resolved. Do not use any memory of how a
question resolved or of how a price moved around it: reason from the mechanism. If you do remember either, set
`remembered: true`.

## What you are given

- `events`: event clusters. Each has an id (`cluster`) and its `questions`: Polymarket yes/no questions that belong to
  one real-world event. Each question has `id`, `question`, `volume_musd` (total traded, $ million), `start`,
  `deadline` (the scheduled end date) and `main`. Exactly one question per cluster has `main: true`: the one the
  grouping code picked (for a ladder its furthest deadline that still trades; otherwise the largest volume).
- `instruments`: US-listed stocks and ETFs by class. The first ticker of a class is its standard instrument.

## What you return for every cluster

1. `family`
   - `spot_proxy`: only if the question is settled by a traded market price, an index level, a yield, an exchange
     rate or a market capitalisation, or by a holder buying or selling a traded asset ("Will Bitcoin reach
     $150,000", "largest company by market cap", "MicroStrategy sells Bitcoin").
   - `event`: anything else a listed instrument would react to: an official decision, an official statistic (CPI,
     GDP, payrolls, a recession call), a vote, a ruling, a war, a deal, a ranking, even when prices influence it.
     If in doubt between `event` and `spot_proxy`, answer `event`.
   - `none`: nothing a listed instrument would react to, or you cannot tell.
2. `structure`
   - `binary`: one question. Also use `binary` when the cluster's questions are independent of each other (neither
     nested nor mutually exclusive): answer for the `main` question alone.
   - `ladder`: nested questions, where Yes on one implies Yes on another ("by June" implies "by December"; "above
     100" implies "above 80").
   - `multi_outcome`: at most one of the questions can resolve Yes ("candidate X wins", "exactly 2 cuts", "cut 25 /
     no change / hike 25"). If each outcome also has several deadlines, use only its latest-deadline question.
3. `signal`: the question or questions that carry the event, with weights.
   - `binary` and `ladder`: exactly one entry, the `main` question with weight 1. Always. Do not pick another rung.
   - `multi_outcome`: the weights describe the event along one axis, which you name in `signal_meaning`. They never
     depend on an instrument.
     - Outcomes on one side of the axis get positive weights, outcomes on the other side negative weights, numbers
       in [-1, 1]. Leave out the outcomes that are neutral or unclear. Which side you make positive does not
       matter: the code lines the two labellers up.
     - Weight every question that belongs to a side. `main` is only the largest by volume and can be a long shot:
       do not build the signal on it for that reason.
     - A central-bank meeting, always: hike 50 or more = 1, hike 25 = 0.5, no change left out, cut 25 = -0.5, cut 50
       or more = -1.
     - A count ("how many cuts", "how many seats"): weights that rise with the number, from -1 for the smallest to
       1 for the largest.
     - An election or a nomination: the candidates of one camp (party, bloc or policy side) positive, the
       candidates of the opposing camp negative, the rest left out.
   - `signal_meaning`: one sentence, what a rise in the signal means.
   - `alternative`: what gains when the signal falls. Every direction below is measured against this.
4. `links`: at most 4 instruments, the most direct first. For each:
   - `ticker`: upper case, as its primary US exchange shows it, with "." for a share class (BRK.B).
   - `direction`: `up_on_yes` if the instrument rises when the signal rises, `down_on_yes` if it falls.
   - `confidence`, 0 to 1: that an overnight move in the signal shows up in the instrument's opening gap, in that
     direction, after taking out the move of the US market as a whole.
   - `impact_pct`: a positive number. The instrument's move in percent, after taking out its beta times the US
     market, if the signal went from its lowest possible value to its highest (for a binary: from certain No to
     certain Yes). The sign is carried by `direction`, not here.
   - `mechanism_class`: one of `commodity_supply`, `rates_policy`, `fx_macro`, `country_election`,
     `regulation_sector`, `company_specific`, `crypto_policy`, `war_geopolitics`, `trade_tariffs`, `other`.
   - `mechanism`: one sentence.
   - `off_menu`: true if the ticker is not in `instruments`, else false.
5. `no_instrument` (true or false) and `no_instrument_reason`.
6. `market_wide`: `up`, `down` or null: the direction of the US market as a whole when the signal rises. It may be
   given together with links.
7. `remembered`: true if you remember how the question resolved or how any price reacted to it.

## Rules for links

- **A link needs `impact_pct` of 1 or more**, measured after taking out beta times the market. An instrument that
  moves more only because it moves more with the market (QQQ, IWM, a high-beta sector) is never a link.
- **Never name SPY.**
- **Naming, so that two labellers agree.** Choose the class of exposure first. Within a class, name its first
  listed ticker before any other ticker of that class. Add a second ticker of the same class only when it carries a
  different exposure (crude oil itself, then the producers). For a meeting of the Federal Reserve: the first ticker
  of `rates_short`. For a foreign election: the country's ETF first, then at most two of its largest companies on
  the list.
- **Off the list only when no class covers the exposure.**
- **The direction must hold against the alternative you wrote.** If you cannot name the alternative, there is no link.
- **Do not judge whether an outcome is likely.** A question with a mechanism gets its link even if it looks remote.
  The code measures whether the odds move.
- **"No listed instrument" is a full answer** and is better than a weak link. Use it when nothing listed in the US
  would move 1%.
- For a `spot_proxy`, link the asset itself. It is reported as a price proxy, not as an event link.

## Output

Write one JSON object to the answer file you were told, and nothing else there:

```json
{"labeller": "<the name you were given>", "chunk": <number>, "answers": [
  {"cluster": "c001", "family": "event", "structure": "ladder",
   "signal": [{"id": "polymarket:123", "weight": 1}],
   "signal_meaning": "...", "alternative": "...",
   "links": [{"ticker": "USO", "direction": "up_on_yes", "confidence": 0.6, "impact_pct": 6,
              "mechanism_class": "commodity_supply", "mechanism": "...", "off_menu": false}],
   "no_instrument": false, "no_instrument_reason": "", "market_wide": null, "remembered": false}
]}
```

## Hard rules, checked by code

An answer that breaks one of these is discarded and its cluster gets no link.

- Every cluster in `events` gets exactly one answer, in the same order, and every field above is present.
- `binary` and `ladder`: `signal` is exactly the `main` question with weight 1.
- `multi_outcome`: every `id` in `signal` is one of the cluster's question ids, every weight is a number in
  [-1, 1], and at least one weight is not 0.
- `links` is empty when `no_instrument` is true or `family` is `none`. At most 4 links. No ticker twice. Never SPY.
