import type { Async } from "@/lib/hooks";
import type { HedgeMenu as Menu } from "@/lib/api";
import { money } from "@/lib/hooks";
import { Badge, ErrorText, Loading } from "./ui";

export function HedgeMenu({ menu, selected, onPick }: { menu: Async<Menu>; selected: string | null; onPick: (s: string) => void }) {
  const m = menu.data;
  return (
    <div className="space-y-2">
      {menu.loading && <Loading what="hedge menu" />}
      {menu.error && <ErrorText>Hedge menu failed: {menu.error}</ErrorText>}
      {m && m.options.length === 0 && <p className="text-sm text-slate-500">No hedge options available. {m.notes.join(" ")}</p>}
      {m?.options.map((o) => (
        <button key={o.strategy} onClick={() => onPick(o.strategy)} className={`w-full rounded-2xl border bg-white/80 p-3 text-left hover:bg-white ${selected === o.strategy ? "border-indigo-400 ring-2 ring-indigo-200" : "border-white/70"}`}>
          <div className="flex items-center justify-between"><span className="font-medium">{o.rank}. {o.strategy.replaceAll("_", " ")}</span>{o.rank === 1 && <Badge tone="info">top ranked</Badge>}</div>
          <p className="text-xs text-slate-600">{o.covers}</p>
          <p className="mt-1 text-xs text-slate-700">
            Premium {money(o.premium_total)} ({money(o.premium_per_share)}/sh) · max loss {money(o.max_loss_per_share)}/sh · breakeven {money(o.breakeven_price)} · fees {money(o.fees)}
            {o.half_spread_cost != null && ` · half-spread ${money(o.half_spread_cost)}`}
          </p>
          <p className="mt-1 text-xs italic text-slate-500">{o.why}</p>
        </button>
      ))}
      {m && m.notes.length > 0 && m.options.length > 0 && m.notes.map((n) => <p key={n} className="text-xs text-amber-700">{n}</p>)}
    </div>
  );
}
