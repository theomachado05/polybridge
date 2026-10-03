"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { getEquity, getHedges, listVerdicts, mapEvent, searchMarkets, type Direction, type Market, type VerdictLabel } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { EquityPanel } from "@/components/EquityPanel";
import { HedgeMenu } from "@/components/HedgeMenu";
import { MappingList } from "@/components/MappingList";
import { MarketCard } from "@/components/MarketCard";
import { ProposePanel } from "@/components/ProposePanel";
import { SearchBox } from "@/components/SearchBox";
import { StepCards } from "@/components/StepCards";
import { VerdictCard } from "@/components/VerdictCard";
import { ErrorText, Glass, Loading, Nav, StaleBadge } from "@/components/ui";

const isTicker = (q: string) => /^[A-Z]{1,5}(\.[A-Z])?$/.test(q);
const looksLikeTicker = (q: string) => /^[A-Za-z]{1,5}(\.[A-Za-z])?$/.test(q);
const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function Build() {
  const sp = useSearchParams();
  const pre = sp.get("ticker")?.toUpperCase() ?? null;
  const [query, setQuery] = useState<string | null>(pre);
  const [market, setMarket] = useState<Market | null>(null);
  const [picked, setPicked] = useState<string | null>(pre);
  const [filingIdx, setFilingIdx] = useState<number | null>(null);
  const [strategy, setStrategy] = useState<string | null>(null);
  const [shares, setShares] = useState(Number(sp.get("shares")) || 100);

  const asTicker = query && (isTicker(query) || query === pre) ? query.toUpperCase() : null;
  const ticker = picked ?? asTicker;

  const search = useAsync(query && !asTicker ? `s:${query}` : null, () => searchMarkets(query!));
  const verdicts = useAsync(query && !asTicker ? "verdicts" : null, listVerdicts);
  const typedVerdict = query && verdicts.data ? verdicts.data.find((v) => norm(v.tag) === norm(query) && v.kind !== "none") ?? null : null;
  const equity = useAsync(ticker ? `e:${ticker}` : null, () => getEquity(ticker!));
  const map = useAsync(market ? `m:${market.source}:${market.id}` : null, () => mapEvent({ question: market!.question, source: market!.source, market_id: market!.id }));

  const filing = equity.data && filingIdx != null ? equity.data.filings[filingIdx] ?? null : null;
  const verdict = filing?.verdict ?? typedVerdict ?? equity.data?.filings[0]?.verdict ?? null;
  const tags = filing?.tags ?? (typedVerdict ? [typedVerdict.tag] : equity.data?.filings[0]?.tags ?? null);
  const label: VerdictLabel = verdict?.label ?? "no_edge";
  const hedges = useAsync(ticker && shares > 0 ? `h:${ticker}:${shares}:${label}` : null, () => getHedges(ticker!, shares, label));

  const markets = search.data?.markets ?? (asTicker || picked ? equity.data?.markets : undefined) ?? [];
  const item = map.data?.items.find((i) => i.ticker === ticker);
  const direction: Direction | null = item ? (item.direction === "up_on_yes" ? "up_on_yes" : "down_on_yes") : null;

  const reset = (q: string) => { setQuery(q); setMarket(null); setPicked(null); setFilingIdx(null); setStrategy(null); };

  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-6xl space-y-5 px-6 py-6">
        <SearchBox initial={pre ?? ""} onSearch={reset} />
        <StepCards steps={[
          { title: "Event", value: market ? market.question : asTicker ? `Stock ${asTicker}` : null, hint: "Search a question, a ticker or a filing type" },
          { title: "Equity", value: ticker, hint: "Pick the stock the event hits" },
          { title: "Hedge", value: strategy ? strategy.replaceAll("_", " ") : null, hint: "Choose a ranked, fee-aware hedge" },
        ]} />
        {!query && <p className="text-sm text-slate-600">Start with a search above.</p>}
        <div className="grid gap-5 lg:grid-cols-3">
          <Glass className="space-y-3">
            <div className="flex items-center justify-between"><h2 className="font-semibold">Event</h2>{search.data?.stale && <StaleBadge />}</div>
            {search.loading && <Loading what="markets" />}
            {search.error && <ErrorText>Market search failed: {search.error}</ErrorText>}
            {search.data && markets.length === 0 && <p className="text-sm text-slate-500">No open markets found for that search.</p>}
            {equity.loading && asTicker && <Loading what="related markets" />}
            {markets.slice(0, 8).map((m) => <MarketCard key={`${m.source}:${m.id}`} market={m} selected={market?.id === m.id} onSelect={() => setMarket(m)} />)}
            {verdicts.loading && <Loading what="filing-type verdicts" />}
            {verdicts.error && <ErrorText>Verdict lookup failed: {verdicts.error}</ErrorText>}
            {typedVerdict && <VerdictCard v={typedVerdict} />}
            {query && !asTicker && looksLikeTicker(query) && (
              <button className="text-sm text-indigo-700 hover:underline" onClick={() => { setPicked(query.toUpperCase()); setFilingIdx(null); }}>Look up {query.toUpperCase()} as a ticker</button>
            )}
            {market && <MappingList map={map} selected={picked} onPick={(t) => { setPicked(t); setFilingIdx(null); setStrategy(null); }} />}
          </Glass>
          <Glass className="space-y-3">
            <h2 className="font-semibold">Equity</h2>
            {!ticker && <p className="text-sm text-slate-500">Choose a stock from the mapping, or search a ticker.</p>}
            {equity.loading && <Loading what={`${ticker} card`} />}
            {equity.error && <ErrorText>Equity lookup failed: {equity.error}</ErrorText>}
            {equity.data && <EquityPanel card={equity.data} filingIdx={filingIdx} onPickFiling={setFilingIdx} />}
            {verdict && <div className="border-t border-white/70 pt-3"><VerdictCard v={verdict} /></div>}
          </Glass>
          <Glass className="space-y-3">
            <h2 className="font-semibold">Hedge</h2>
            {!ticker && <p className="text-sm text-slate-500">Pick a stock first.</p>}
            {ticker && <HedgeMenu menu={hedges} selected={strategy} onPick={setStrategy} />}
            {ticker && <div className="border-t border-white/70 pt-3"><ProposePanel key={`${ticker}:${market?.id ?? ""}`} ticker={ticker} tags={tags} shares={shares} onShares={setShares} market={market} spot={hedges.data?.spot ?? equity.data?.implied_move?.spot ?? null} mappedImpact={item?.impact_pct ?? null} direction={direction} strategy={strategy} /></div>}
          </Glass>
        </div>
      </main>
    </>
  );
}

export default function BuildPage() {
  return <Suspense fallback={<p className="p-8">Loading...</p>}><Build /></Suspense>;
}
