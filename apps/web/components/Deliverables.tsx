"use client";
/** Deliverables — generated artefacts (XLSX / DOCX / PDF) with citations.
 *
 * The renderers produce all three formats for real, so this pane lists what
 * the project has actually emitted — read from disk, not from what this
 * browser session happened to witness — each with its download link and
 * citation count.
 *
 * Filter, search and sort exist because artefacts accumulate fast: one
 * afternoon of work leaves a dozen files whose names are all derived from the
 * prompt that made them, which means they all start with the same words.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { DeliverableRec, ProvenanceCitation } from "@/lib/types";
import {
  Badge,
  Button,
  EmptyState,
  IconButton,
  SearchInput,
  SegmentedControl,
  Select,
  Spinner,
  cn,
} from "./ui";
import { IconDownload, IconEye, IconRefresh, IconTable, fileIcon } from "./icons";

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
    <div className={compact ? "mt-3 space-y-1.5" : "space-y-1.5"}>
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
  const Glyph = fileIcon(d.kind);

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
    <div
      className={cn(
        "group/d rounded-xl border bg-ink-850 transition-colors",
        open ? "border-ink-700" : "border-ink-800 hover:border-ink-700",
      )}
    >
      <div className="flex items-center gap-3 px-3 py-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-ink-800 text-accent">
          <Glyph size={16} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium text-zinc-100">
            {d.name}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-[10px] text-zinc-600">
            <span className="text-zinc-500">
              {KIND_LABEL[d.kind] ?? KIND_LABEL.other}
            </span>
            <span>{new Date(d.created_at).toLocaleString()}</span>
            {d.size_bytes ? <span>{humanSize(d.size_bytes)}</span> : null}
          </span>
        </span>

        {d.citations !== undefined && (
          <Badge
            color={d.citations > 0 ? "green" : "amber"}
            className="hidden shrink-0 sm:inline-flex"
          >
            {d.citations} cited
          </Badge>
        )}

        {projectId && (
          <IconButton
            icon={<IconEye size={15} />}
            label={open ? "Hide sources" : "Show sources"}
            size="sm"
            active={open}
            onClick={() => void toggle()}
          />
        )}
        <a
          href={d.url}
          download
          title={`Download ${d.name}`}
          aria-label={`Download ${d.name}`}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-zinc-500 transition-colors hover:bg-accent/10 hover:text-accent"
        >
          <IconDownload size={15} />
        </a>
      </div>

      {open && (
        <div className="border-t border-ink-800 px-3 py-2.5">
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
                  <span className="min-w-0 truncate text-zinc-300">
                    {c.label}
                  </span>
                  <span className="ml-auto shrink-0 font-mono text-[10px] text-zinc-600">
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

type SortKey = "newest" | "oldest" | "name" | "citations";

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
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<string>("all");
  const [sort, setSort] = useState<SortKey>("newest");

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
  const all = useMemo(() => {
    const seen = new Set((stored ?? []).map((d) => d.name));
    return [...(stored ?? []), ...items.filter((d) => !seen.has(d.name))];
  }, [stored, items]);

  const kinds = useMemo(() => {
    const present = new Set(all.map((d) => (d.kind || "other").toLowerCase()));
    return ["all", ...Array.from(present).sort()];
  }, [all]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = all.filter(
      (d) =>
        (kind === "all" || (d.kind || "other").toLowerCase() === kind) &&
        (!q || d.name.toLowerCase().includes(q)),
    );
    const byTime = (d: DeliverableRec) => new Date(d.created_at).getTime() || 0;
    return [...filtered].sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "oldest") return byTime(a) - byTime(b);
      if (sort === "citations") return (b.citations ?? 0) - (a.citations ?? 0);
      return byTime(b) - byTime(a);
    });
  }, [all, kind, query, sort]);

  const totalCitations = all.reduce((n, d) => n + (d.citations ?? 0), 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 px-5 py-2.5">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search artefacts…"
          className="w-56"
        />
        {kinds.length > 2 && (
          <SegmentedControl
            size="sm"
            value={kind}
            onChange={setKind}
            ariaLabel="Filter by file type"
            options={kinds.map((k) => ({
              value: k,
              label: k === "all" ? "All" : (KIND_LABEL[k] ?? k.toUpperCase()),
            }))}
          />
        )}
        <Select
          value={sort}
          onChange={(v) => setSort(v as SortKey)}
          ariaLabel="Sort artefacts"
          options={[
            { value: "newest", label: "Newest first" },
            { value: "oldest", label: "Oldest first" },
            { value: "name", label: "Name A–Z" },
            { value: "citations", label: "Most cited" },
          ]}
        />
        <div className="ml-auto flex items-center gap-2">
          <span className="font-mono text-[11px] text-zinc-600">
            {visible.length === all.length
              ? `${all.length} files · ${totalCitations} citations`
              : `${visible.length} of ${all.length}`}
          </span>
          <IconButton
            icon={<IconRefresh size={15} />}
            label="Re-read the deliverables folder"
            size="sm"
            disabled={refreshing}
            onClick={() => void load()}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {error && (
          <div className="mb-3 rounded-xl border border-rose-900/50 bg-rose-950/30 px-3.5 py-2.5 text-xs text-rose-300">
            {error}
          </div>
        )}
        {stored === null ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner /> Loading deliverables…
          </div>
        ) : visible.length > 0 ? (
          <DeliverableCards items={visible} projectId={projectId} />
        ) : all.length > 0 ? (
          <EmptyState
            icon={<IconTable size={18} />}
            title="Nothing matches those filters"
            hint="Clear the search or switch the type filter back to All."
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setQuery("");
                  setKind("all");
                }}
              >
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={<IconTable size={18} />}
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

      <div className="border-t border-ink-800 px-5 py-2.5 text-[11px] leading-relaxed text-zinc-600">
        <span className="font-medium text-zinc-500">How these are made:</span> a
        bounded agent loop (max 3 replans, 12 tool calls, 180s) calls typed
        tools only. Numbers come from the deterministic calculation engine,
        never from the model, and every artefact ships a provenance sidecar
        listing the source behind each section.
      </div>
    </div>
  );
}
