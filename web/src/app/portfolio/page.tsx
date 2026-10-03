"use client";

import { getPortfolio } from "@/lib/api";
import { money, useAsync } from "@/lib/hooks";
import { HoldingCard } from "@/components/HoldingCard";
import { ErrorText, Glass, Loading, Nav, StaleBadge } from "@/components/ui";

export default function PortfolioPage() {
  const pf = useAsync("portfolio", getPortfolio);
  const d = pf.data;
  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-6xl space-y-5 px-6 py-6">
        <div className="flex items-center gap-3"><h1 className="text-xl font-semibold">Portfolio exposure map</h1>{d?.stale && <StaleBadge />}</div>
        {pf.loading && <Loading what="portfolio (searches live markets, can take a few seconds)" />}
        {pf.error && <ErrorText>Portfolio failed to load: {pf.error}</ErrorText>}
        {d && (
          <Glass className="flex flex-wrap gap-6 text-sm">
            <span>Total value <strong>{money(d.total_value)}</strong></span>
            <span>Remaining event exposure <strong>{money(d.total_exposure)}</strong>{d.total_includes_fuzzy && <span className="ml-1 text-xs text-amber-700">(includes fuzzy-matched mappings: closest-question matches, less reliable)</span>}</span>
            <span className="text-xs text-slate-500">Exposure = shares × spot × impact% × (1 − yes price) when YES lowers the stock, × yes price when YES raises it, from AI estimates (precomputed).</span>
          </Glass>
        )}
        {d && d.holdings.length === 0 && <p className="text-sm text-slate-500">No holdings configured.</p>}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">{d?.holdings.map((h) => <HoldingCard key={h.ticker} h={h} />)}</div>
      </main>
    </>
  );
}
