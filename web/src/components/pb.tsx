import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { sparkPath } from "@/lib/fmt";

export function Orb({ state, size, ink = "#0F1626", style }: { state: string; size: number; ink?: string; style?: CSSProperties }) {
  return <thinking-orb state={state} size={String(size)} ink={ink} style={{ display: "inline-block", width: size, height: size, ...style }} />;
}

export function Glass({ children, style, className = "" }: { children: ReactNode; style?: CSSProperties; className?: string }) {
  return <div className={`pb-glass ${className}`} style={style}>{children}</div>;
}

export function Label({ children, style, rule, color }: { children: ReactNode; style?: CSSProperties; rule?: boolean; color?: string }) {
  return <div className={`pb-label${rule ? " pb-rule" : ""}`} style={{ color, ...style }}>{children}</div>;
}

type BtnKind = "primary" | "secondary" | "disabled";
export function Btn({ children, kind = "primary", onClick, href, style, title }: {
  children: ReactNode; kind?: BtnKind; onClick?: () => void; href?: string; style?: CSSProperties; arrow?: boolean; title?: string;
}) {
  const cls = `pb-btn pb-btn-${kind}`;
  const inner = children;
  if (href && kind !== "disabled") return <Link href={href} className={cls} style={style} onClick={onClick} title={title}>{inner}</Link>;
  return <button type="button" className={cls} style={style} onClick={kind === "disabled" ? undefined : onClick} disabled={kind === "disabled"} title={title}>{inner}</button>;
}

export function Chip({ on, children, onClick, small }: { on: boolean; children: ReactNode; onClick: () => void; small?: boolean }) {
  return <button type="button" className={`pb-chip${small ? " pb-chip-sm" : ""}`} data-on={on} onClick={onClick}>{children}</button>;
}

export function ChipGroup<T extends string>({ label, options, value, onChange }: { label: string; options: readonly T[]; value: T; onChange: (v: T) => void }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 500 }}>{label}</div>
      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
        {options.map((o) => <Chip key={o} on={o === value} onClick={() => onChange(o)}>{o}</Chip>)}
      </div>
    </div>
  );
}

export function Switch({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} className="pb-switch" data-on={on} onClick={onClick}><span /></button>;
}

export function LogoTile({ logo }: { logo: string }) {
  return <span className="pb-logo"><span style={{ backgroundImage: `url(${logo})` }} /></span>;
}

export type TagTone = "demo" | "replay" | "live" | "sim" | "paper" | "ai" | "measured" | "caution" | "neutral";
const TAG: Record<TagTone, { bg: string; fg: string }> = {
  demo: { bg: "#FBF0D4", fg: "#7A5000" },
  replay: { bg: "#E9EEF9", fg: "#1F3F99" },
  live: { bg: "#E2F3EA", fg: "#11673F" },
  sim: { bg: "#ECEDF0", fg: "#3C4458" },
  paper: { bg: "#E9EEF9", fg: "#2B57D6" },
  ai: { bg: "#ECEDF0", fg: "#3C4458" },
  measured: { bg: "#E2F3EA", fg: "#11673F" },
  caution: { bg: "#FCE9D9", fg: "#8A4200" },
  neutral: { bg: "#ECEDF0", fg: "#5A627A" },
};
export function Tag({ tone, children, title }: { tone: TagTone; children: ReactNode; title?: string }) {
  const t = TAG[tone];
  return <span className="pb-tag" style={{ background: t.bg, color: t.fg }} title={title}>{children}</span>;
}
export function Unavailable({ what, error, onRetry, style, compact }: { what: string; error?: string | null; onRetry?: () => void; style?: CSSProperties; compact?: boolean }) {
  return (
    <div role="alert" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: compact ? 12 : 13, color: "#8A5A00", lineHeight: 1.45, ...style }}>
      <span className="pb-pretty" style={{ minWidth: 0 }}>{what}: not available{error ? ` (${error})` : ""}.</span>
      {onRetry && <button type="button" className="pb-chip pb-chip-sm" data-on={false} onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Spark({ data, color, w = 150, h = 56 }: { data: number[]; color: string; w?: number; h?: number }) {
  const d = sparkPath(data, 300, h);
  return (
    <svg viewBox={`0 0 300 ${h}`} width={w} height={h} preserveAspectRatio="none" style={{ display: "block", overflow: "visible", flex: "1 1 90px", minWidth: 0, maxWidth: w }}>
      {d && <path d={d} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" />}
    </svg>
  );
}

export function OrbDisc({ state, disc, orb }: { state: string; disc: number; orb: number }) {
  return (
    <div style={{ position: "relative", width: disc, height: disc, display: "flex", alignItems: "center", justifyContent: "center", flex: "none" }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "var(--surface)", border: "1px solid var(--border)" }} />
      <Orb state={state} size={orb} ink="#1E2A4A" style={{ position: "relative" }} />
    </div>
  );
}

export const panel: CSSProperties = { padding: "22px 26px", minWidth: 0 };
export const upColor = (n: number) => (n >= 0 ? "#15804F" : "#C8323F");
export const upColorBright = (n: number) => (n >= 0 ? "#22A06B" : "#E0485A");
