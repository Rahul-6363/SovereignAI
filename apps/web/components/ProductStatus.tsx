"use client";
/** Product status — makes the completed / in-progress boundary explicit.
 *
 * README §8 (Slide 3) and §13 Day 6 require that "completed" and "in progress"
 * claims are consistent and explicit everywhere the product is shown.
 */
import { cn } from "./ui";

export default function ProductStatus({ className }: { className?: string }) {
  const rows = [
    {
      key: "Completed",
      tone: "emerald" as const,
      text: "P&ID upload + processing + existing P&ID interface. Treat as a working product module.",
    },
    {
      key: "Starting now",
      tone: "amber" as const,
      text: "Main Claude-like Meshcore workspace, with a visible P&ID capability that opens the completed P&ID interface.",
    },
    {
      key: "Next",
      tone: "zinc" as const,
      text: "Connect agent, retrieval, deterministic calculations, security, audit, and file deliverables to the common workspace.",
    },
  ];
  const tones = {
    emerald: "border-emerald-900/70 bg-emerald-950/20 text-emerald-300",
    amber: "border-amber-900/70 bg-amber-950/20 text-amber-300",
    zinc: "border-ink-700 bg-ink-850 text-zinc-400",
  };
  return (
    <div className={cn("grid gap-2 sm:grid-cols-3", className)}>
      {rows.map((r) => (
        <div
          key={r.key}
          className={cn("rounded-xl border p-3", tones[r.tone])}
        >
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider">
            {r.key}
          </div>
          <p className="text-[11px] leading-relaxed text-zinc-500">{r.text}</p>
        </div>
      ))}
    </div>
  );
}