"use client";
/** Capability cards / launcher (README §0.1, §8 VISUAL 1).
 *
 * P&ID is a first-class capability here. Selecting it hands off to the
 * *existing* P&ID upload/processing interface — the new home screen never
 * duplicates the P&ID workflow (README §0.1).
 */
import type { ReactElement } from "react";
import type { Capability, CapabilityStatus } from "@/lib/types";
import { Badge, cn } from "./ui";
import {
  IconCode,
  IconGraph,
  IconMessage,
  IconSchematic,
  IconShieldCheck,
  IconSigma,
  IconLock,
  IconTable,
} from "./icons";

/** id -> glyph. Kept beside the grid rather than on the `Capability`
 *  record because the record is data (it crosses the type boundary in
 *  `lib/types`), and a React element is not. */
const CAPABILITY_ICON: Record<string, (p: { size?: number }) => ReactElement> = {
  pid: IconSchematic,
  agent: IconMessage,
  memory: IconGraph,
  deliverables: IconTable,
  calculate: IconSigma,
  retrieval: IconLock,
  trust: IconShieldCheck,
  sandbox: IconCode,
};

/** Single source of truth for capability + maturity, matching README §7. */
export const CAPABILITIES: Capability[] = [
  {
    id: "pid",
    name: "P&ID → Plant Memory",
    blurb:
      "Upload a drawing; symbols, tags and connections become a typed, queryable graph.",
    status: "available",
  },
  {
    id: "agent",
    name: "Agent workspace",
    blurb:
      "Ask in plain language. Grounded answers with a visible tool/activity trace.",
    status: "available",
  },
  {
    id: "memory",
    name: "Plant Memory graph",
    blurb:
      "Explore equipment, lines and instruments. Every node carries a confidence score.",
    status: "available",
  },
  {
    id: "deliverables",
    name: "Deliverable studio",
    blurb:
      "Ask in plain language and get a real XLSX, DOCX or PDF with citations — not a chat reply to copy out by hand.",
    status: "available",
  },
  {
    id: "calculate",
    name: "Deterministic calculation",
    blurb:
      "Typed calculation requests run in a unit-checked engine. The model never does arithmetic.",
    status: "phase2",
  },
  {
    id: "retrieval",
    name: "Clearance-aware retrieval",
    blurb:
      "ACL applied as an index pre-filter, so a lower clearance cannot leak restricted content.",
    status: "phase1",
  },
  {
    id: "trust",
    name: "Provable sovereignty",
    blurb:
      "Default-deny egress with a live attempt counter, hash-chained audit trail.",
    status: "available",
  },
  {
    id: "sandbox",
    name: "Code sandbox",
    blurb:
      "Generated code runs in a network-isolated sandbox with a read-only filesystem.",
    status: "phase2",
  },
];

const STATUS_STYLE: Record<
  CapabilityStatus,
  { label: string; color: "green" | "amber" | "zinc"; dot: boolean }
> = {
  available: { label: "Available", color: "green", dot: true },
  phase1: { label: "Phase 1", color: "amber", dot: false },
  phase2: { label: "Phase 2", color: "zinc", dot: false },
  planned: { label: "Roadmap", color: "zinc", dot: false },
};

export function CapabilityStatusBadge({ status }: { status: CapabilityStatus }) {
  const s = STATUS_STYLE[status];
  return (
    <Badge color={s.color} dot={s.dot}>
      {s.label}
    </Badge>
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
        const Icon = CAPABILITY_ICON[c.id];
        const live = c.status === "available";
        return (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={cn(
              "group flex h-full flex-col items-start gap-2 rounded-2xl border p-4 text-left transition-colors",
              live
                ? "border-ink-800 bg-ink-850 shadow-raised hover:border-ink-700 hover:bg-ink-800/70"
                : "border-dashed border-ink-800 bg-transparent hover:border-ink-700",
            )}
          >
            <div className="flex w-full items-center gap-2.5">
              <span
                className={cn(
                  "grid h-8 w-8 shrink-0 place-items-center rounded-xl",
                  live
                    ? "bg-accent/12 text-accent"
                    : "bg-ink-850 text-zinc-600",
                )}
              >
                {Icon ? <Icon size={16} /> : null}
              </span>
              <span
                className={cn(
                  "min-w-0 flex-1 truncate text-[13px] font-medium",
                  live ? "text-zinc-100" : "text-zinc-400",
                )}
              >
                {c.name}
              </span>
            </div>
            <p className="text-[12px] leading-relaxed text-zinc-500">
              {c.blurb}
            </p>
            <div className="mt-auto flex w-full items-center pt-1.5">
              <CapabilityStatusBadge status={c.status} />
              {live && (
                <span className="ml-auto text-[11px] text-zinc-700 transition-colors group-hover:text-accent">
                  Open
                </span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
