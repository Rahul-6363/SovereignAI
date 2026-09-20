"use client";
/** Upload + live ingestion pipeline checklist (README UI state B). */
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { DocumentRec, IngestionStatus } from "@/lib/types";
import { Badge, Button, Spinner, cn } from "./ui";

const POLL_MS = 1500;

/** stage → UI checklist mapping (backend stages: validating, rendering,
 *  extracting, building_memory, indexing, index_ready, error). */
function stepIndex(stage: string): number {
  // Multi-page extraction reports "extracting:2/7" so the label can show
  // progress; the checklist only cares about the stage before the colon.
  switch (stage.split(":")[0]) {
    case "uploaded":
    case "queued":
    case "validating":
      return 1;
    case "rendering":
      return 2;
    case "extracting":
      return 3;
    case "building_memory":
      return 4;
    case "indexing":
      return 5;
    case "index_ready":
    case "ready":
      return 6;
    default:
      return 1;
  }
}

const STEPS = [
  "File uploaded",
  "Pages rendered",
  "P&ID entities detected",
  "Building Plant Memory",
  "Indexing evidence",
  "Ready",
];

export default function UploadIngest({
  projectId,
  docs,
  activeDocId,
  onSelectDoc,
  onIngested,
  onDocDeleted,
}: {
  projectId: number;
  docs: DocumentRec[];
  activeDocId: number | null;
  onSelectDoc: (d: DocumentRec) => void;
  onIngested: (docId: number, status: IngestionStatus) => void;
  onDocDeleted: (docId: number) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pipeline, setPipeline] = useState<{
    doc: DocumentRec;
    status: IngestionStatus;
  } | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  // An in-flight poll must not outlive the component — navigating away mid
  // ingest otherwise leaves an interval calling setState on an unmounted tree.
  useEffect(() => stopPolling, []);

  const poll = (docId: number) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.ingestStatus(docId);
        setPipeline((p) => (p ? { ...p, status } : p));
        if (status.status === "ready" || status.status === "failed") {
          stopPolling();
          setBusy(false);
          onIngested(docId, status);
        }
      } catch {
        stopPolling();
        setBusy(false);
      }
    }, POLL_MS);
  };

  const handleFile = async (file: File) => {
    if (!projectId || busy) return;
    setBusy(true);
    setError("");
    try {
      const doc = await api.uploadDocument(projectId, file);
      setPipeline({
        doc,
        status: {
          document_id: doc.id,
          status: doc.status,
          stage: doc.stage,
          progress: 0,
          pages: 0,
          entities: 0,
          relationships: 0,
          error: "",
        },
      });
      onSelectDoc(doc);
      await api.ingestDocument(doc.id);
      poll(doc.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  /** Re-run ingestion for a document that failed or never finished.
   *  Without this a failed drawing could only be deleted and re-uploaded. */
  const retry = async (doc: DocumentRec) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setPipeline({
        doc,
        status: {
          document_id: doc.id,
          status: "processing",
          stage: "queued",
          progress: 0,
          pages: 0,
          entities: 0,
          relationships: 0,
          error: "",
        },
      });
      onSelectDoc(doc);
      await api.ingestDocument(doc.id);
      poll(doc.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const deleteDoc = async (doc: DocumentRec) => {
    if (busy) return;
    if (
      !confirm(
        `Delete "${doc.name}" and its extracted entities, links and evidence?`
      )
    )
      return;
    setError("");
    try {
      await api.deleteDocument(doc.id);
      setPipeline((p) => (p?.doc.id === doc.id ? null : p));
      if (pipelineDocId === doc.id) stopPolling();
      onDocDeleted(doc.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const pipelineDocId = pipeline?.doc.id ?? null;
  const stageIdx = pipeline ? stepIndex(pipeline.status.stage) : 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,image/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void handleFile(f);
          e.target.value = "";
        }}
      />
      <Button
        variant="outline"
        onClick={() => fileRef.current?.click()}
        disabled={busy}
        className="w-full"
      >
        {busy ? <Spinner /> : "+"} Upload a P&ID
      </Button>
      {pipeline && (
        <div className="mt-2 rounded-lg border border-ink-700 bg-ink-850 p-2">
          <div className="mb-1 truncate text-xs font-medium text-zinc-300">
            {pipeline.doc.name}
          </div>
          <ul className="space-y-1">
            {STEPS.map((s, i) => {
              const done =
                pipeline.status.status === "ready" ? i < 5 : i < stageIdx - 1;
              const active =
                pipeline.status.status !== "ready" && i === stageIdx - 1;
              const failed =
                pipeline.status.status === "failed" && i === stageIdx - 1;
              return (
                <li key={s} className="flex items-center gap-2 text-[11px]">
                  <span
                    className={cn(
                      "grid h-3.5 w-3.5 place-items-center rounded-full border text-[9px]",
                      done
                        ? "border-emerald-700 bg-emerald-950 text-emerald-400"
                        : failed
                          ? "border-rose-700 bg-rose-950 text-rose-400"
                          : active
                            ? "border-amber-700 bg-amber-950 text-amber-400"
                            : "border-ink-600 text-zinc-600",
                    )}
                  >
                    {done ? "✓" : failed ? "✕" : active ? "●" : ""}
                  </span>
                  <span
                    className={cn(
                      done
                        ? "text-zinc-400"
                        : active
                          ? "text-zinc-200"
                          : "text-zinc-600",
                    )}
                  >
                    {s}
                  </span>
                  {/* "2/7" from stage "extracting:2/7" — on a multi-page
                      sheet this is the only sign the run is still moving. */}
                  {active && pipeline.status.stage.includes(":") && (
                    <span className="text-[10px] text-amber-500">
                      {pipeline.status.stage.split(":")[1]}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          {pipeline.status.error && (
            <p className="mt-1 text-[11px] text-rose-400">
              {pipeline.status.error}
            </p>
          )}
        </div>
      )}
      {error && <p className="mt-2 text-[11px] text-rose-400">{error}</p>}
      <ul className="mt-3 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {docs.map((d) => (
          <li
            key={d.id}
            className={cn(
              "group flex items-center gap-1 rounded-md px-2 py-1.5 text-xs",
              d.id === activeDocId
                ? "bg-ink-700 text-zinc-100"
                : "text-zinc-400 hover:bg-ink-800",
            )}
          >
            <button
              onClick={() => onSelectDoc(d)}
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  d.status === "ready"
                    ? "bg-emerald-400"
                    : d.status === "failed"
                      ? "bg-rose-500"
                      : "animate-pulse-dot bg-amber-400",
                )}
              />
              <span
                className="truncate flex-1"
                title={d.error ? `${d.name} — ${d.error}` : d.name}
              >
                {d.name}
              </span>
              {d.page_count > 0 && (
                <Badge color="zinc" className="shrink-0">
                  {d.page_count}p
                </Badge>
              )}
            </button>
            {d.status === "failed" && (
              <button
                onClick={() => void retry(d)}
                disabled={busy}
                title="Retry ingestion for this document"
                className="shrink-0 rounded px-1 text-amber-400 transition-colors hover:text-amber-300 disabled:opacity-40"
              >
                ↻
              </button>
            )}
            <button
              onClick={() => void deleteDoc(d)}
              title="Delete this document"
              className="shrink-0 rounded px-1 text-zinc-600 opacity-0 transition-opacity hover:text-rose-400 focus:opacity-100 group-hover:opacity-100"
            >
              ✕
            </button>
          </li>
        ))}
        {docs.length === 0 && (
          <li className="px-2 py-1 text-xs text-zinc-600">No files yet</li>
        )}
      </ul>
    </div>
  );
}
