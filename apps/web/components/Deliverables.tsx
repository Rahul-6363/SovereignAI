"use client";
/** Deliverables — generated artefacts (XLSX / DOCX / PDF) with citations.
 *
 * README §0.1 requires a "generated deliverables" area. The renderers now
 * produce all three formats for real, so this pane lists what the project
 * has actually emitted — read from disk, not from what this browser session
 * happened to witness — each with its download link and citation count.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DeliverableRec, ProvenanceCitation } from "@/lib/types";
import { Badge, Button, EmptyState, Spinner, cn } from "./ui";

const KIND_LABEL: Record<string, string> = {
  docx: "DOCX",
  xlsx: "XLSX",
  pdf: "PDF",
  code: "CODE",
  other: "FILE",
};

function humanSize(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DeliverableCards({
  items,
  compact = false,
  projectId,
}: {
  items: DeliverableRec[];
  compact?: boolean;
  projectId?: number;
}) {
  if (items.length === 0) return null;
  return (
    <div className={compact ? "mt-2 space-y-1.5" : "space-y-2"}>
      {items.map((d) => (
        <DeliverableRow key={d.id} item={d} projectId={projectId} />
      ))}
    </div>
  );
}

function DeliverableRow({
  item: d,
  projectId,
}: {
  item: DeliverableRec;
  projectId?: number;
}) {
  const [open, setOpen] = useState(false);
  const [cites, setCites] = useState<ProvenanceCitation[] | null>(null);
  const [loading, setLoading] = useState(false);

  // Provenance is the point of the artefact, so it is one click away rather
  // than a separate file the reviewer has to know to look for.
  const toggle = useCallback(async () => {
    const next = !open;
    setOpen(next);
    if (!next || cites || !projectId) return;
    setLoading(true);
    try {
      const prov = await api.deliverableProvenance(projectId, d.name);
      setCites(prov.citations ?? []);
    } catch {
      setCites([]);
    } finally {
      setLoading(false);
    }
  }, [open, cites, projectId, d.name]);

  return (
    <div className="rounded-xl border border-ink-700 bg-ink-850">
      <div className="flex items-center gap-3 px-3 py-2">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ink-700 font-mono text-[10px] font-semibold text-accent">
          {KIND_LABEL[d.kind] ?? KIND_LABEL.other}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium text-zinc-100">
            {d.name}
          </span>
          <span className="font-mono text-[10px] text-zinc-500">
            {new Date(d.created_at).toLocaleString()}
            {d.citations !== undefined ? ` · ${d.citations} citations` : ""}
            {d.size_bytes ? ` · ${humanSize(d.size_bytes)}` : ""}
          </span>
        </span>
        {projectId && (
          <button
            onClick={() => void toggle()}
            className="shrink-0 rounded-md px-2 py-1 text-[11px] text-zinc-500 transition-colors hover:bg-ink-800 hover:text-zinc-300"
          >
            {open ? "Hide sources" : "Sources"}
          </button>
        )}
        <a
          href={d.url}
          className="shrink-0 rounded-md px-2 py-1 text-[11px] text-accent transition-colors hover:bg-accent/10"
        >
          Download ↓
        </a>
      </div>

      {open && (
        <div className="border-t border-ink-800 px-3 py-2">
          {loading && (
            <div className="flex items-center gap-2 text-[11px] text-zinc-500">
              <Spinner className="h-3 w-3" /> Loading provenance…
            </div>
          )}
          {!loading && cites && cites.length === 0 && (
            <p className="text-[11px] text-zinc-600">
              No citations recorded for this artefact.
            </p>
          )}
          {!loading && cites && cites.length > 0 && (
            <ul className="space-y-1">
              {cites.map((c, i) => (
                <li key={i} className="flex items-baseline gap-2 text-[11px]">
                  <span className="shrink-0 font-mono text-zinc-600">
                    {c.section ?? "—"}
                  </span>
                  <span className="truncate text-zinc-300">{c.label}</span>
                  <span className="ml-auto shrink-0 font-mono text-[10px] text-zinc-500">
                    {c.document || c.source_type}
                    {c.page ? ` p${c.page}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function DeliverablesPane({
  items,
  projectId,
}: {
  items: DeliverableRec[];
  projectId: number;
}) {
  const [stored, setStored] = useState<DeliverableRec[] | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      setStored(await api.deliverables(projectId));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStored([]);
    } finally {
      setRefreshing(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load, items.length]);

  // Artefacts persist on disk, so the pane shows what the project has ever
  // produced — not just what this browser session happened to witness.
  const seen = new Set((stored ?? []).map((d) => d.name));
  const all = [...(stored ?? []), ...items.filter((d) => !seen.has(d.name))];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-ink-800 px-6 py-3">
        <span className="text-sm font-medium text-zinc-200">Deliverables</span>
        <Badge color={all.length > 0 ? "green" : "amber"}>
          {all.length > 0 ? `${all.length} produced` : "none yet"}
        </Badge>
        <Button
          variant="outline"
          onClick={() => void load()}
          disabled={refreshing}
          className="ml-auto px-2 py-1 text-xs"
        >
          {refreshing ? <Spinner className="h-3 w-3" /> : "↻"} Refresh
        </Button>
        <span className="shrink-0 font-mono text-[11px] text-zinc-600">
          project {projectId}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {error && (
          <div className="mb-3 rounded-lg border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {error}
          </div>
        )}
        {stored === null ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner /> Loading deliverables…
          </div>
        ) : all.length > 0 ? (
          <DeliverableCards items={all} projectId={projectId} />
        ) : (
          <EmptyState
            title="No deliverables yet"
            hint={
              "Just ask in the chat — “generate an excel of all instruments”, " +
              "“draft a PDF change note for valve XV-101”. The format comes " +
              "from your sentence; each artefact is rendered with citations " +
              "and a machine-readable provenance sidecar."
            }
          />
        )}
      </div>

      <div className="border-t border-ink-800 px-6 py-3 text-[11px] leading-relaxed text-zinc-500">
        <span className="font-semibold text-zinc-400">How these are made:</span>{" "}
        a bounded agent loop (max {"3"} replans, {"12"} tool calls, {"180"}s)
        calls typed tools only. Numbers come from the deterministic calculation
        engine, never from the model, and every artefact ships a provenance
        sidecar listing the source behind each section.
      </div>
    </div>
  );
}
