"use client";
/** Tool / activity trace for one agent turn.
 *
 * Renders the operational steps the agent took so a refinery engineer can see
 * *how* an answer was produced — not just the answer. Steps are emitted live
 * from the SSE stream and from local tool actions (attachment upload).
 *
 * Laid out as a timeline rather than a list: the left rule and the node on
 * each row make the sequence readable at a glance, which is the only thing
 * anyone wants from it when a five-step package run is halfway through.
 */
import type { ActivityStep } from "@/lib/types";
import { cn } from "./ui";
import { IconCheck, IconX } from "./icons";

function Node({ status }: { status: ActivityStep["status"] }) {
  if (status === "done")
    return (
      <span className="grid h-4 w-4 place-items-center rounded-full border border-emerald-800 bg-emerald-950 text-emerald-400">
        <IconCheck size={9} />
      </span>
    );
  if (status === "failed")
    return (
      <span className="grid h-4 w-4 place-items-center rounded-full border border-rose-800 bg-rose-950 text-rose-400">
        <IconX size={9} />
      </span>
    );
  if (status === "active")
    return (
      <span className="grid h-4 w-4 place-items-center rounded-full border border-amber-800 bg-amber-950">
        <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-amber-400" />
      </span>
    );
  return (
    <span className="grid h-4 w-4 place-items-center rounded-full border border-ink-700 bg-ink-900">
      <span className="h-1 w-1 rounded-full bg-ink-600" />
    </span>
  );
}

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
        "relative space-y-1.5 rounded-xl border border-ink-800 bg-ink-850/40 p-3 text-[11px]",
        className,
      )}
    >
      {steps.map((s, i) => (
        <li key={s.id} className="relative flex items-start gap-2.5">
          {/* the rule between nodes, drawn per-row so it stops at the last */}
          {i < steps.length - 1 && (
            <span
              aria-hidden
              className="absolute left-[7px] top-4 h-full w-px bg-ink-800"
            />
          )}
          <span className="relative z-10 mt-[1px] shrink-0">
            <Node status={s.status} />
          </span>
          <span className="min-w-0 flex-1">
            <span
              className={cn(
                "block leading-snug",
                s.status === "active"
                  ? "text-zinc-200"
                  : s.status === "failed"
                    ? "text-rose-300"
                    : s.status === "done"
                      ? "text-zinc-400"
                      : "text-zinc-600",
              )}
            >
              {s.label}
            </span>
            {s.detail && (
              <span className="mt-0.5 block truncate font-mono text-[10px] text-zinc-600">
                {s.detail}
              </span>
            )}
          </span>
          <span className="shrink-0 font-mono text-[10px] text-zinc-700">
            {s.at}
          </span>
        </li>
      ))}
    </ol>
  );
}
