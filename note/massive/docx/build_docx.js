// Builds note/massive/PolyBridge_Massive_8K.docx in the two-page stock-pitch format.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, AlignmentType,
  HorizontalPositionRelativeFrom, VerticalPositionRelativeFrom, HorizontalPositionAlign,
  TextWrappingType, TextWrappingSide,
} = require("docx");

const DIR = __dirname;
const FONT = "Arial";
const SIZE = 22; // half-points: 11pt

// Parse "**bold**" and "*italic*" inline markers into runs.
function runs(text) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, size: SIZE }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, font: FONT, size: SIZE }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, font: FONT, size: SIZE }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, size: SIZE }));
  return out;
}

function para(text, opts = {}) {
  const children = [];
  if (opts.image) children.push(opts.image);
  children.push(...runs(text));
  return new Paragraph({
    children,
    alignment: opts.align || AlignmentType.JUSTIFIED,
    spacing: { after: opts.after ?? 90, line: 252 },
  });
}

function floatImage(file, wIn, hIn, offsetIn = 0) {
  return new ImageRun({
    type: "png",
    data: fs.readFileSync(path.join(DIR, file)),
    transformation: { width: Math.round(wIn * 96), height: Math.round(hIn * 96) },
    floating: {
      horizontalPosition: { relative: HorizontalPositionRelativeFrom.MARGIN, align: HorizontalPositionAlign.RIGHT },
      verticalPosition: { relative: VerticalPositionRelativeFrom.PARAGRAPH, offset: Math.round(offsetIn * 914400) },
      wrap: { type: TextWrappingType.SQUARE, side: TextWrappingSide.LEFT },
      margins: { left: 114300, bottom: 45720, top: 0 },
    },
  });
}

const title = new Paragraph({
  spacing: { after: 60 },
  children: [new TextRun({
    text: "(MASSIVE 8-K) PolyBridge: NO TRADE – The Option Chain Already Priced the Headline",
    bold: true, font: FONT, size: 24,
  })],
});

const stats = new Paragraph({
  spacing: { after: 100 },
  children: runs("Universe: **Top 100 US stocks** | Events: **60** in-sample, **11** out-of-sample | Verdict: **H1 NULL**, **H2 NULL** | Mispricing bound: **3.0%** (H1), **0.9%** (H2) | Net edge after costs: **+11 bp**"),
});

const body = [
  para("**Investment Thesis:** The option chain is the professional price of an event. In our main-track study, on **4,561** fresh Polymarket stock markets, pre-registered and run once, the option-implied probability was the more accurate forecast (Brier difference **+0.0108**, 95% CI +0.0064 to +0.0158). So we use the chain as our ruler and ask, like a market maker, where it could bend after an 8-K. We pre-registered two places. After slow-burning bad news, dealers mark volatility down once the headline passes while the damage resolves over weeks (**H1: buy the protective put**). After restructurings, holders who must sit through the event bid for puts that dealers cannot offset (**H2: sell the cash-secured put**). We recommend **NO TRADE**: the chain priced both within tight bounds. Over 2024–2025 post-headline protection was not under-priced by more than **3.0%** of the stock price, and restructuring puts were not over-priced by more than **0.9%**. The one bend we found came out of sample and went the other way: in 2026 restructurings moved **2.2–2.5x** the implied move in their first week."),

  para("**Data and Universe:** Massive’s Filings & Disclosures dataset tags every 8-K since 2022 with one of 119 event types. From the descriptions alone, before any event or price was fetched, we committed 11 tags: **7 for H1** (material litigation, class actions, regulatory investigations, cyber incidents, goodwill, asset and investment impairments) and **4 for H2** (restructuring plans, workforce reductions, facility closures, business-line exits). The universe is the starter’s top 100. In-sample (2024–2025) gives **60** events, 28–33 H1 and 23–24 H2 with a P&L at each horizon; **5** filings tagged in both families are dropped from both. Out-of-sample (January–August 2026, run once after the method freeze) gives **3** H1 and **8** H2 events. Options are 3–6 months out with the put **5%** out of the money; spot comes from put-call parity; the baseline is **120** ordinary days per family for the same companies."),

  para("**Why the chain should bend after slow bad news (H1):** An 8-K is priced once, on the day it lands. Implied volatility falls when the headline passes, but litigation, investigations and impairments resolve over weeks, so the chain should over-charge for day one and under-charge for the follow-through. We measure that with the parity ratio, |realized move| ÷ the move the chain priced the session before. In-sample H1 has exactly that shape: **0.68** one session after the filing against **0.99** on ordinary days, and **1.36** at 42 sessions against **1.15** (Graph 1). Each hypothesis must show both a P&L edge and the predicted ratio sign, so a strategy that is merely short volatility in a calm year cannot pass. H1’s shape is real but sits inside its 95% band: with about 30 events, the bend is not distinguishable from a straight ruler.",
    { image: floatImage("graph1_decay.png", 3.75, 2.5, 0.02) }),

  para("**Why restructurings should carry a put premium (H2):** Holders who must keep the stock through a restructuring buy puts, and dealers charge for one-sided demand they cannot hedge (Gârleanu, Pedersen and Poteshman, 2009). In-sample the sign is there: the short put beats ordinary days at 21 sessions, 42 sessions and expiry, and in **9 of 9** sensitivity cells. The size is not: **+0.09%** at 21 sessions [−0.68, +0.89]. The first session points the same way as the mechanism: a put sold the day after the filing loses **−0.25%** [−0.52, −0.02] against ordinary days, consistent with put demand arriving after the headline (one of nine horizons, not corrected for multiple tests)."),

  para("**How we tested it:** Hypotheses, tags, pass rule and forecast were committed to git before any data (HYPOTHESIS.md, HYPOTHESIS_TAGS.md, FORECAST.md); the out-of-sample run sits behind a frozen tag (method-freeze) and a one-run guard. **Entry is conservative:** every filing is treated as public after the close, so the trade enters at the close of the next session and never trades on an intraday filing it could not have seen. **Pass rule:** the 97.5% bootstrap interval of the edge over ordinary days lies above zero at **2 or more** of 21 sessions, 42 sessions and expiry, with the ratio moving the predicted way there. Fewer than 2 testable horizons is **INSUFFICIENT**, not NULL."),

  para("**What is new in our link:** The starter pairs a filing category with a strategy; we pair it with a pricing mechanism and test both its P&L and its fingerprint on the chain. The parity ratio turns “did the trade make money” into “where in the option’s life did the chain misprice”, so even a null locates the error: day one or the follow-through. The two families were chosen to bend the ruler in **opposite directions** (H1 under-priced risk, H2 over-priced demand), so one volatility regime cannot make both pass. And the conservative entry, the cross-family exclusion and the placebo on the same names were fixed before any data, which is what makes the bounds worth quoting."),

  para("**What we found:** Neither hypothesis passes, in or out of sample (Graph 2). In-sample both are **NULL**: H1’s edge is **+0.07%** at 21 sessions [−2.70, +2.91], **+0.49%** at 42 and **+3.33%** at expiry; H2’s is **+0.09%**, **+0.21%** and **+0.92%**, every headline interval straddling zero. Out of sample H1 is **INSUFFICIENT** (3 events) and H2 is **NULL with its sign reversed**: **−2.15%** at 21 sessions [−7.59, +2.03] and **−1.38%** at 42. The decay curve shows why: 2026 restructurings moved far more than priced in the first week (ratio above 1 with 95% confidence at 3 and 5 sessions, 7 events), the opposite of H2. **Sensitivity:** across expiry bucket × OTM distance (3%, 5%, 10%) at 21 sessions, H1’s edge ranges **−0.67%** to **+0.68%** and H2’s **+0.08%** to **+1.24%**. **By category** (exploratory atlas, at most 15 events a tag): no H1 tag clears zero; restructuring plans alone with the cash-secured put do (**+2.57%** at expiry [+0.95, +4.51], 14 events, q = 0.014), a lead for the next pre-registered test, not a result.",
    { image: floatImage("graph2_edges.png", 3.75, 2.5, 0.02) }),

  para("**Trade realism:** As specified, the trade buys (H1) or sells cash-secured (H2) the 5%-out-of-the-money 3–6-month put at the next close and exits at 21 sessions. A **5%** premium haircut each way costs **28–29 bp** of the stock price; real half-spreads where Massive quotes exist are **26–29 bp**. Net of costs the edge over ordinary days is **+11 bp** for both families, inside the noise (+14 to +15 bp at doubled costs, since the haircut hits events and ordinary days alike). **Capacity:** the median put traded **34** (H1) and **49** (H2) contracts on the entry day, so at 10% participation a desk fills 3–5 contracts an event, about **$0.1M** of stock notional, on roughly **1.3** H1 and **1.0** H2 events a month."),

  para("**Catalyst, the judges’ sealed window:** Before running any window outside 2024–2025 we committed a forecast. Out of sample it got “no pass” and the H2 count right (about 8; 7 reached 21 sessions), and missed the H1 count (about 11; 3 arrived), the interval widths (2–3x wider) and all three signs it could score. **For the sealed window it predicts:** a 3-month window gives about 4 H1 and 3 H2 events, so **INSUFFICIENT** for both; 4–5 months NULL or INSUFFICIENT; 6 months or longer **NULL** for both. A PASS would contradict our forecast. The notebook prints it beside the sealed-window verdict."),

  para("**What a portfolio manager can use:** After these filings, buying protection at the next close does not overpay by more than the bounds above, so a holder who wants the hedge need not wait for implied volatility to fall; selling restructuring puts for a premium is not a strategy at this size. For PolyBridge the result is the one the thesis needs: the chain is a straight enough ruler after corporate headlines to price thinner markets against."),

  para("**How PolyBridge uses the result:** The product gates every signal on its own pre-registered test, in code. Because neither family passed, PolyBridge shows 8-K tags as untested and never lets them size a hedge. The study still does work for the product: it is evidence that the chain is a fair reference after corporate headlines, which is the price we hold thinner prediction markets against. If the sealed window or the 2026 follow-up passes, the gate opens for that family alone."),

  para("**Risks to our call: (1) Too few events to see a real edge.** *Mitigant:* we state bounds, not “no effect”; a litigation or cyber wave adds power and the forecast says what it would take. **(2) Spot is inferred and marks are daily last trades.** *Mitigant:* entry and exit use the same construction, so the error largely cancels, and real half-spreads confirm the haircut. **(3) Static top-100 list (survivorship).** *Mitigant:* events and ordinary days come from the same companies, so the bias largely nets out of the edge. **(4) The 2026 first-week bend is real.** *Mitigant:* it is our next pre-registered test, on a window with power to detect a 0.5% edge.",
    { after: 0 }),
];

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: SIZE } } } },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 720, bottom: 720, left: 792, right: 792 },
      },
    },
    children: [title, stats, ...body],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  const out = path.join(DIR, "..", "PolyBridge_Massive_8K.docx");
  fs.writeFileSync(out, buf);
  console.log("wrote", out);
});
