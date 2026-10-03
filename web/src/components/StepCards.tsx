import { Glass } from "./ui";

export interface Step { title: string; value: string | null; hint: string }

export function StepCards({ steps }: { steps: Step[] }) {
  const active = steps.findIndex((s) => s.value === null);
  return (
    <ol className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-stretch">
      {steps.flatMap((s, i) => {
        const done = s.value !== null;
        const card = (
          <li key={s.title} className="list-none">
            <Glass className={`h-full ${i === active ? "ring-2 ring-indigo-300" : ""}`}>
              <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Step {i + 1} · {s.title}</p>
              <p className={`mt-1 text-sm ${done ? "font-medium" : "text-slate-500"}`}>{done ? s.value : s.hint}</p>
            </Glass>
          </li>
        );
        return i < steps.length - 1
          ? [card, <li key={`${s.title}-link`} aria-hidden className="hidden list-none self-center text-xl text-indigo-300 md:block">→</li>]
          : [card];
      })}
    </ol>
  );
}
