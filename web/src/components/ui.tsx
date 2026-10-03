import Link from "next/link";
import type { ReactNode } from "react";

export function Glass({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-[20px] border border-white/70 bg-white/70 p-5 shadow-sm backdrop-blur-xl ${className}`}>{children}</section>;
}

const TONES: Record<string, string> = {
  neutral: "bg-slate-100 text-slate-600",
  good: "bg-emerald-100 text-emerald-700",
  warn: "bg-amber-100 text-amber-700",
  bad: "bg-rose-100 text-rose-700",
  info: "bg-indigo-100 text-indigo-700",
};

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: keyof typeof TONES; title?: string }) {
  return <span title={title} className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>;
}

export const StaleBadge = () => <Badge tone="warn" title="Live source failed; showing the last cached result">stale (cached)</Badge>;

export function Loading({ what }: { what: string }) {
  return <p className="animate-pulse text-sm text-slate-500">Loading {what}...</p>;
}

export function ErrorText({ children }: { children: ReactNode }) {
  return <p role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{children}</p>;
}

export function Btn({ children, onClick, disabled, kind = "primary" }: { children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: "primary" | "ghost" }) {
  const base = "rounded-full px-4 py-1.5 text-sm font-medium transition disabled:opacity-50";
  const k = kind === "primary" ? "bg-indigo-600 text-white hover:bg-indigo-500" : "border border-indigo-200 bg-white/70 text-indigo-700 hover:bg-white";
  return <button className={`${base} ${k}`} onClick={onClick} disabled={disabled}>{children}</button>;
}

export function Nav() {
  return (
    <nav className="mx-auto flex max-w-6xl items-center gap-5 px-6 pt-6 text-sm">
      <Link href="/" className="text-base font-semibold">PolyBridge</Link>
      <Link href="/build" className="text-indigo-700 hover:underline">Build</Link>
      <Link href="/portfolio" className="text-indigo-700 hover:underline">Portfolio</Link>
    </nav>
  );
}
