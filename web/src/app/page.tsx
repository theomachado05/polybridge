import { Glass, Nav } from "@/components/ui";

const SCREENS = [
  { href: "/build", title: "Build", text: "Search an event, a ticker or a filing type. See the verdict, the affected stocks and a ranked hedge, then approve it." },
  { href: "/portfolio", title: "Portfolio", text: "Exposure map of the demo holdings: open markets, recent filings and verdicts, remaining event exposure, hedge status." },
];

export default function Home() {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-4xl space-y-6 px-6 py-10">
        <h1 className="text-4xl font-semibold">PolyBridge</h1>
        <p className="text-slate-700">Prediction-market prices in, approved hedges out. Bridges open from an approved hedge proposal, at <code>/bridge/&lt;id&gt;</code>.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          {SCREENS.map((s) => (
            <a key={s.href} href={s.href}><Glass className="h-full transition hover:bg-white/90"><h2 className="text-lg font-semibold">{s.title}</h2><p className="mt-1 text-sm text-slate-600">{s.text}</p></Glass></a>
          ))}
        </div>
      </main>
    </>
  );
}
