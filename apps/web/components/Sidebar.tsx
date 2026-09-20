"use client";
/** Left rail: Meshcore brand, capability shortcuts, projects, files
 *  (+upload/ingestion), memory counts, trust. */
import Link from "next/link";
import { api } from "@/lib/api";
import type { DocumentRec, IngestionStatus, Project } from "@/lib/types";
import { cn } from "./ui";
import UploadIngest from "./UploadIngest";

export default function Sidebar({
  projects,
  projectId,
  docs,
  activeDocId,
  onSelectDoc,
  onIngested,
  onDocDeleted,
  onOpenTrust,
  localOk,
}: {
  projects: Project[];
  projectId: number;
  docs: DocumentRec[];
  activeDocId: number | null;
  onSelectDoc: (d: DocumentRec) => void;
  onIngested: (docId: number, status: IngestionStatus) => void;
  onDocDeleted: (docId: number) => void;
  onOpenTrust: () => void;
  localOk: boolean | null;
}) {
  const project = projects.find((p) => p.id === projectId);
  const entCount = project?.stats.entities ?? 0;
  const relCount = project?.stats.relationships ?? 0;

  return (
    <aside className="flex h-full w-[260px] shrink-0 flex-col border-r border-ink-700 bg-ink-950">
      {/* brand + capability shortcuts */}
      <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-accent font-bold text-white">
          M
        </span>
        <Link href="/" className="truncate text-sm font-semibold text-zinc-100">
          Meshcore
        </Link>
        <button
          onClick={onOpenTrust}
          title="Open Trust Center"
          className={cn(
            "ml-auto rounded-md border px-1.5 py-0.5 text-[10px] font-medium",
            localOk === null
              ? "border-ink-600 text-zinc-500"
              : localOk
                ? "border-emerald-900 bg-emerald-950/40 text-emerald-300"
                : "border-rose-900 bg-rose-950/40 text-rose-300",
          )}
        >
          {localOk === null ? "…" : localOk ? "Local ●" : "Offline"}
        </button>
      </div>

      <nav className="border-b border-ink-700 px-3 py-2">
        <div className="mb-1 px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Capabilities
        </div>
        <Link
          href={`/projects/${projectId}?view=pid&from=meshcore`}
          className="mb-0.5 block rounded-md px-2 py-1.5 text-sm text-accent transition-colors hover:bg-accent/10"
        >
           P&amp;ID <span className="text-[10px] text-emerald-400">done</span>
        </Link>
        <Link
          href={`/projects/${projectId}?view=chat`}
          className="block rounded-md px-2 py-1.5 text-sm text-zinc-400 transition-colors hover:bg-ink-800 hover:text-zinc-200"
        >
          ✦ Agent chat
        </Link>
        <Link
          href={`/projects/${projectId}?view=memory`}
          className="block rounded-md px-2 py-1.5 text-sm text-zinc-400 transition-colors hover:bg-ink-800 hover:text-zinc-200"
        >
          ⬡ Plant Memory
        </Link>
        <Link
          href="/"
          className="block rounded-md px-2 py-1.5 text-sm text-zinc-500 transition-colors hover:bg-ink-800 hover:text-zinc-300"
        >
          ← Meshcore home
        </Link>
      </nav>

      {/* projects */}
      <div className="px-3 pt-4">
        <div className="mb-1 px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Projects
        </div>
        <ul className="space-y-0.5">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className={cn(
                  "block truncate rounded-md px-2 py-1.5 text-sm",
                  p.id === projectId
                    ? "bg-ink-700 text-zinc-100"
                    : "text-zinc-400 hover:bg-ink-800 hover:text-zinc-200",
                )}
              >
                {p.name}
              </Link>
            </li>
          ))}
          {projects.length === 0 && (
            <li className="px-2 py-1.5 text-xs text-zinc-600">No projects yet</li>
          )}
        </ul>
      </div>

      {/* files + ingestion */}
      <div className="mt-5 flex min-h-0 flex-1 flex-col px-3">
        <div className="mb-1 px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Files
        </div>
        <UploadIngest
          projectId={projectId}
          docs={docs}
          activeDocId={activeDocId}
          onSelectDoc={onSelectDoc}
          onIngested={onIngested}
          onDocDeleted={onDocDeleted}
        />
      </div>

      {/* memory summary */}
      <div className="border-t border-ink-700 px-4 py-3 text-xs text-zinc-500">
        <div className="mb-1 font-semibold uppercase tracking-wider text-zinc-500">
          Memory
        </div>
        <div className="flex justify-between">
          <span>Entities</span>
          <span className="font-mono text-zinc-300">{entCount}</span>
        </div>
        <div className="flex justify-between">
          <span>Links</span>
          <span className="font-mono text-zinc-300">{relCount}</span>
        </div>
        <button
          onClick={onOpenTrust}
          className="mt-2 text-[11px] text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
        >
          Trust Center & audit log →
        </button>
      </div>
    </aside>
  );
}
