"use client";
/** Inspector drawer (right): entity details or chat evidence, with preview. */
import { useState } from "react";
import type { EntityDetail } from "@/lib/types";
import { Badge, ConfidenceBar, IconButton, Spinner, cn } from "./ui";
import { IconEye, IconX } from "./icons";
import PidViewer from "./PidViewer";

export default function Inspector({
  detail,
  loading,
  error,
  onClose,
}: {
  detail: EntityDetail | null;
  loading: boolean;
  error: string;
  onClose: () => void;
}) {
  // Nothing to inspect yet: collapse to a rail instead of holding 340px of
  // empty panel open across the drawing and the chat.
  const empty = !loading && !error && !detail;
  if (empty) {
    return (
      <aside
        title="Inspector — click an entity, a memory node or an evidence chip"
        className="flex h-full w-9 shrink-0 flex-col items-center gap-2 border-l border-ink-800 bg-ink-950 py-3"
      >
        <IconEye size={15} className="text-zinc-600" />
        <span
          className="text-[10px] font-semibold uppercase tracking-widest text-zinc-600"
          style={{ writingMode: "vertical-rl" }}
        >
          Inspector
        </span>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-[340px] shrink-0 flex-col border-l border-ink-800 bg-ink-950">
      <div className="flex items-center justify-between border-b border-ink-800 px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Inspector
        </span>
        <IconButton
          icon={<IconX size={14} />}
          label="Close the inspector"
          size="sm"
          onClick={onClose}
        />
      </div>

      {loading && (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-zinc-500">
          <Spinner /> Loading…
        </div>
      )}
      {!loading && error && (
        <div className="m-3 rounded-lg border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
          {error}
        </div>
      )}
      {!loading && !error && detail && <EntityInspector detail={detail} />}
    </aside>
  );
}

function EntityInspector({ detail }: { detail: EntityDetail }) {
  const e = detail.entity;
  const conn = detail.connections ?? [];
  const [tab, setTab] = useState<"details" | "preview">("details");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-ink-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <Badge color={e.confidence >= 0.8 ? "green" : "amber"}>
            {e.entity_type}
          </Badge>
          <span className="truncate font-mono text-sm text-zinc-100">
            {e.canonical_tag || e.raw_text || "—"}
          </span>
        </div>
        {e.label && e.label !== e.canonical_tag && (
          <p className="mt-0.5 text-xs text-zinc-500">{e.label}</p>
        )}
      </div>

      <div className="flex gap-1 border-b border-ink-800 px-3 py-1.5">
        {(["details", "preview"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs transition-colors",
              t === tab
                ? "bg-ink-700 text-zinc-100"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            {t === "details" ? "Details" : "Preview"}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "preview" ? (
          <div className="h-full min-h-[240px]">
            <PidViewer
              imageUrl={detail.image_url}
              bbox={e.bbox}
              label={e.canonical_tag}
            />
          </div>
        ) : (
          <div className="space-y-4 text-xs">
            <section>
              <div className="mb-1 font-semibold uppercase tracking-wider text-zinc-500">
                Confidence
              </div>
              <ConfidenceBar value={e.confidence} />
            </section>

            <section>
              <div className="mb-1 font-semibold uppercase tracking-wider text-zinc-500">
                Source
              </div>
              <div className="rounded-lg border border-ink-700 bg-ink-850 p-2 text-zinc-400">
                <div className="truncate">{detail.source_document || "—"}</div>
                <div className="text-zinc-600">
                  {detail.page_number ? `page ${detail.page_number}` : ""}
                </div>
              </div>
              {e.bbox && e.bbox.length === 4 && (
                <p className="mt-1 font-mono text-[10px] text-zinc-600">
                  bbox [{e.bbox.map((n) => n.toFixed(3)).join(", ")}]
                </p>
              )}
            </section>

            <section>
              <div className="mb-1 font-semibold uppercase tracking-wider text-zinc-500">
                Connections ({conn.length})
              </div>
              <ul className="space-y-1">
                {conn.map((r) => {
                  const outgoing = r.source_tag === e.canonical_tag;
                  return (
                    <li
                      key={r.id}
                      className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-850 px-2 py-1.5"
                    >
                      <span className="font-mono text-[11px] text-accent-soft">
                        {outgoing ? r.target_tag : r.source_tag}
                      </span>
                      <span className="text-[10px] text-zinc-500">
                        {outgoing ? "→" : "←"} {r.relationship_type}
                      </span>
                      <span className="ml-auto font-mono text-[10px] text-zinc-600">
                        {Math.round(r.confidence * 100)}%
                      </span>
                    </li>
                  );
                })}
                {conn.length === 0 && (
                  <li className="text-zinc-600">No links recorded</li>
                )}
              </ul>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}