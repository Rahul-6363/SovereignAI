"use client";
/** Capability cards / launcher (README §0.1, §8 VISUAL 1).
 *
 * P&ID is a first-class capability here. Selecting it hands off to the
 * *existing* P&ID upload/processing interface — the new home screen never
 * duplicates the P&ID workflow (README §0.1).
 */
import type { Capability, CapabilityStatus } from "@/lib/types";
import { cn } from "./ui";

/** Single source of truth for capability + maturity, matching README §7. */
export const CAPABILITIES: Capability[] = [
  {
    id: "pid",
    name: "P&ID → Plant Memory",
    blurb:
      "Upload a drawing; symbols, tags and connections become a typed, queryable graph.",
    status: "available",
    icon: "",
  },
  {
    id: "agent",
    name: "Agent workspace",
    blurb:
      "Ask in plain language. Grounded answers with a visible tool/activity trace.",
    status: "available",
    icon: "✦",
  },
  {
    id: "memory",
    name: "Plant Memory graph",
    blurb:
      "Explore equipment, lines and instruments. Every node carries a confidence score.",
    status: "available",
    icon: "⬡",
  },
  {
    id: "deliverables",
    name: "Deliverable studio",
    blurb:
      "Ask in plain language and get a real XLSX, DOCX or PDF with citations — not a chat reply to copy out by hand.",
    status: "phase1",
    icon: "▤",
  },
  {
    id: "calculate",
    name: "Deterministic calculation",
    blurb:
      "Typed calculation requests run in a unit-checked engine. The model never does arithmetic.",
    status: "phase2",
    icon: "∑",
  },
  {
    id: "retrieval",
    name: "Clearance-aware retrieval",
    blurb:
      "ACL applied as an index pre-filter, so a lower clearance cannot leak restricted content.",
    status: "phase2",
    icon: "⛨",
  },
  {
    id: "trust",
    name: "Provable sovereignty",
    blurb:
      "Default-deny egress with a live attempt counter, hash-chained audit trail.",
    status: "available",
    icon: "▲",
  },
  {
    id: "sandbox",
    name: "Code sandbox",
    blurb:
      "Generated code runs in a network-isolated sandbox with a read-only filesystem.",
    status: "phase2",
    icon: "▣",
  },
];

const STATUS_STYLE: Record<CapabilityStatus, { label: string; cls: string }> = {
  available: {
    label: "Available now",
    cls: "border-emerald-900 bg-emerald-950/40 text-emerald-300",
  },
  phase1: {
    label: "Phase 1",
    cls: "border-amber-900 bg-amber-950/40 text-amber-300",
  },
  phase2: {
    label: "Phase 2",
    cls: "border-zinc-700 bg-ink-800 text-zinc-400",
  },
  planned: {
    label: "Roadmap",
    cls: "border-zinc-700 bg-ink-800 text-zinc-500",
  },
};

export function CapabilityStatusBadge({ status }: { status: CapabilityStatus }) {
  const s = STATUS_STYLE[status];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium",
        s.cls,
      )}
    >
      {s.label}
    </span>
  );
}

export default function CapabilityGrid({
  capabilities = CAPABILITIES,
  onSelect,
  columns = 2,
  className,
}: {
  capabilities?: Capability[];
  onSelect: (id: string) => void;
  columns?: 2 | 3 | 4;
  className?: string;
}) {
  const cols =
    columns === 4
      ? "sm:grid-cols-2 lg:grid-cols-4"
      : columns === 3
        ? "sm:grid-cols-2 lg:grid-cols-3"
        : "sm:grid-cols-2";
  return (
    <div className={cn("grid grid-cols-1 gap-2.5", cols, className)}>
      {capabilities.map((c) => {
        const isPid = c.id === "pid";
        return (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={cn(
              "group flex flex-col items-start gap-1.5 rounded-xl border p-3.5 text-left transition-colors",
              isPid
                ? "border-accent/50 bg-accent/[0.07] hover:border-accent"
                : "border-ink-700 bg-ink-850 hover:border-ink-600",
            )}
          >
            <div className="flex w-full items-center gap-2">
              <span
                className={cn(
                  "grid h-6 w-6 shrink-0 place-items-center rounded-md text-xs",
                  isPid ? "bg-accent/20 text-accent" : "bg-ink-700 text-zinc-400",
                )}
              >
                {c.icon}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-100">
                {c.name}
              </span>
              {isPid && (
                <span className="shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
                  first-class
                </span>
              )}
            </div>
            <p className="text-[11px] leading-relaxed text-zinc-500">
              {c.blurb}
            </p>
            <div className="mt-1 flex w-full items-center">
              <CapabilityStatusBadge status={c.status} />
              <span className="ml-auto text-[11px] text-zinc-600 transition-colors group-hover:text-accent">
                open →
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}