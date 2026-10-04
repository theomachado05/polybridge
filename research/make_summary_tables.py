from pathlib import Path

import pandas as pd

OUT = Path("results/in_sample")


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def summary_tables() -> str:
    out = []
    for fam in ("hedge", "opportunity"):
        pc = pd.read_csv(OUT / f"{fam}_pass_check.csv")
        out.append(f"### {fam}: pass check (97.5% CI)\n\n" + md(pc.round(4)))
        sens = pd.read_csv(OUT / f"{fam}_sensitivity.csv")
        lo, hi = sens.loc[sens.edge.idxmin()], sens.loc[sens.edge.idxmax()]
        out.append(f"### {fam}: sensitivity at h=21 (edge, events minus placebo)\n\n"
                   f"min {lo.edge:+.4f} ({lo.bucket}, {lo.entry}, {lo.otm:.0%} OTM); "
                   f"max {hi.edge:+.4f} ({hi.bucket}, {hi.entry}, {hi.otm:.0%} OTM); "
                   f"positive cells {int((sens.edge > 0).sum())} of {int(sens.edge.notna().sum())}")
        rows = []
        for h in (21, 42, "exp"):
            f = OUT / f"{fam}_costs_h{h}.csv"
            if not f.exists():
                continue
            d = pd.read_csv(f)
            r = {"horizon": h, "n_rows": len(d)}
            for c in ("gross", "net_haircut_1x", "net_haircut_2x", "spread_cost", "net_spread"):
                r[c] = round(d[c].mean(), 4)
                r[f"n_{c}"] = int(d[c].notna().sum())
            r["median_leg_volume"] = d["leg_volume"].median()
            rows.append(r)
        out.append(f"### {fam}: costs (mean P&L per $1 spot; n_* = non-missing rows behind each mean)\n\n"
                   + md(pd.DataFrame(rows)))
        cs = OUT / f"{fam}_cost_summary.csv"
        if cs.exists():
            out.append(f"### {fam}: paired cost summary and net-of-haircut edge (events minus placebo)\n\n"
                       + md(pd.read_csv(cs).round(4)))
    return "\n\n".join(out) + "\n"


if __name__ == "__main__":
    (OUT / "summary_tables.md").write_text(summary_tables())
