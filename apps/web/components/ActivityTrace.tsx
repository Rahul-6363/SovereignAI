"use client";
/** Tool / activity trace for one agent turn (README §0.1, §7 Phase 0, Day 4).
 *
 * Renders the operational steps the agent took so a refinery engineer can see
 * *how* an answer was produced — not just the answer. Steps are emitted live
 * from the SSE `status` stream and from local tool actions (attachment upload).
 */
import type { ActivityStep } from "@/lib/types";
import { cn } from "./ui";

const ICON: Record<ActivityStep["status"], string> = {
  pending: "○",
  active: "●",
  done: "✓",
  failed: "✕",
};

export default function ActivityTrace({
  steps,
  className,
}: {
  steps: ActivityStep[];
  className?: string;
}) {
  if (steps.length === 0) return null;
  return (
    <ol
      className={cn(
        "mb-2 space-y-0.5 border-l border-ink-800 pl-3 text-[11px]",
        className,
      )}
    >
      {steps.map((s) => (
        <li key={s.id} className="flex items-baseline gap-2">
          <span
            className={cn(
              "shrink-0 font-mono",
              s.status === "done"
                ? "text-emerald-400"
                : s.status === "active"
                  ? "animate-pulse-dot text-amber-400"
                  : s.status === "failed"
                    ? "text-rose-400"
                    : "text-zinc-600",
            )}
          >
            {ICON[s.status]}
          </span>
          <span
            className={cn(
              s.status === "active"
                ? "text-zinc-200"
                : s.status === "failed"
                  ? "text-rose-300"
                  : "text-zinc-500",
            )}
          >
            {s.label}
          </span>
          {s.detail && (
            <span className="truncate text-zinc-600">· {s.detail}</span>
          )}
          <span className="ml-auto shrink-0 font-mono text-[10px] text-zinc-600">
            {s.at}
          </span>
        </li>
      ))}
    </ol>
  );
}