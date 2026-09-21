"use client";
/** Product status — makes the shipped / in-progress boundary explicit.
 *
 * This is a claim about the product, so it has to track the product. It
 * previously read "starting now: the main workspace" and "next: connect the
 * agent, calculations, audit and file deliverables" — all of which now ship,
 * which made the app understate itself on its own front page and, worse,
 * meant nobody could trust the line that said what was NOT done.
 */
import { cn } from "./ui";
import { IconCheck, IconClock, IconSigma } from "./icons";

const ROWS = [
  {
    key: "Shipped",
    icon: IconCheck,
    tone: "emerald" as const,
    text:
      "P&ID ingestion and extraction, the Plant Memory graph, grounded chat across four modes, the bounded agent loop, XLSX/DOCX/PDF deliverables with provenance, and the hash-chained audit trail.",
  },
  {
    key: "In progress",
    icon: IconClock,
    tone: "amber" as const,
    text:
      "Clearance-aware retrieval as an index pre-filter, so a lower clearance cannot see restricted content rather than merely not being shown it.",
  },
  {
    key: "Next",
    icon: IconSigma,
    tone: "zinc" as const,
    text:
      "Wider deterministic calculation coverage, and a network-isolated sandbox for running generated code against plant data.",
  },
];

const TONES = {
  emerald: "border-emerald-900/60 bg-emerald-950/20",
  amber: "border-amber-900/60 bg-amber-950/20",
  zinc: "border-ink-800 bg-ink-850",
};

const ICON_TONES = {
  emerald: "text-emerald-400",
  amber: "text-amber-400",
  zinc: "text-zinc-600",
};

export default function ProductStatus({ className }: { className?: string }) {
  return (
    <div className={cn("grid gap-2.5 sm:grid-cols-3", className)}>
      {ROWS.map((r) => {
        const Icon = r.icon;
        return (
          <div
            key={r.key}
            className={cn("rounded-2xl border p-3.5", TONES[r.tone])}
          >
            <div className="mb-1.5 flex items-center gap-1.5">
              <Icon size={13} className={ICON_TONES[r.tone]} />
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-[0.08em]",
                  ICON_TONES[r.tone],
                )}
              >
                {r.key}
              </span>
            </div>
            <p className="text-[11px] leading-relaxed text-zinc-500">{r.text}</p>
          </div>
        );
      })}
    </div>
  );
}
