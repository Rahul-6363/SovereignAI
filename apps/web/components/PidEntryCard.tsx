"use client";
/** P&ID entry card — the click target that opens the EXISTING P&ID interface.
 *
 * README §0.1 / §7 Phase 0: clicking P&ID must open the already-completed
 * P&ID upload + processing interface, and must not duplicate that workflow.
 * This card therefore only resolves *which project* the P&ID capability should
 * open (or creates one), then routes to the existing interface.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button, Spinner, cn } from "./ui";

export default function PidEntryCard({
  projects,
  className,
  onCreated,
}: {
  projects: Project[];
  className?: string;
  onCreated?: (p: Project) => void;
}) {
  const router = useRouter();
  const [projectId, setProjectId] = useState<number | null>(
    projects[0]?.id ?? null,
  );
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const open = (id: number) =>
    router.push(`/projects/${id}?view=pid&from=meshcore`);

  const submit = async () => {
    if (busy) return;
    setError("");
    if (projects.length === 0) {
      const trimmed = name.trim();
      if (!trimmed) {
        setError("Name the project first.");
        return;
      }
      setBusy(true);
      try {
        const created = await api.createProject(trimmed, "P&ID workspace");
        onCreated?.(created);
        open(created.id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setBusy(false);
      }
      return;
    }
    if (projectId) open(projectId);
  };

  const selected = projects.find((p) => p.id === projectId);

  return (
    <div
      className={cn(
        "rounded-xl border border-accent/50 bg-accent/[0.06] p-4",
        className,
      )}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className="grid h-6 w-6 place-items-center rounded-md bg-accent/20 text-xs text-accent">
          
        </span>
        <span className="text-sm font-medium text-zinc-100">
          Open the P&amp;ID capability
        </span>
        <span className="ml-auto rounded-full bg-accent px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
          completed module
        </span>
      </div>
      <p className="mb-3 text-[11px] leading-relaxed text-zinc-500">
        Routes straight into the existing P&amp;ID upload, extraction, review and
        result flow. Nothing is rebuilt here.
      </p>

      {projects.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={projectId ?? ""}
            onChange={(e) => setProjectId(Number(e.target.value))}
            className="min-w-[190px] flex-1 rounded-lg border border-ink-600 bg-ink-900 px-2.5 py-2 text-xs text-zinc-200 focus:border-accent focus:outline-none"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.stats.documents > 0
                  ? ` · ${p.stats.documents} drawing${p.stats.documents === 1 ? "" : "s"}`
                  : " · empty"}
              </option>
            ))}
          </select>
          <Button variant="primary" onClick={() => void submit()} disabled={busy}>
            {busy ? <Spinner /> : "→"} Open P&amp;ID interface
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Refinery Unit A"
            className="min-w-[190px] flex-1 rounded-lg border border-ink-600 bg-ink-900 px-2.5 py-2 text-xs text-zinc-200 placeholder-zinc-600 focus:border-accent focus:outline-none"
          />
          <Button variant="primary" onClick={() => void submit()} disabled={busy}>
            {busy ? <Spinner /> : "+"} Create project &amp; open P&amp;ID
          </Button>
        </div>
      )}

      {selected && selected.stats.documents === 0 && (
        <p className="mt-2 text-[11px] text-amber-300">
          This project has no drawings yet — the interface opens on the upload
          step.
        </p>
      )}
      {error && <p className="mt-2 text-[11px] text-rose-400">{error}</p>}
    </div>
  );
}