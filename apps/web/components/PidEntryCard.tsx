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
import { Badge, Button, Input, Select, cn } from "./ui";
import { IconArrowRight, IconPlus, IconSchematic } from "./icons";

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
        "rounded-2xl border border-accent/30 bg-accent/[0.05] p-4",
        className,
      )}
    >
      <div className="mb-1.5 flex items-center gap-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-accent/15 text-accent">
          <IconSchematic size={16} />
        </span>
        <span className="text-[15px] font-medium text-zinc-100">
          Open the P&amp;ID capability
        </span>
        <Badge color="accent" className="ml-auto">
          complete
        </Badge>
      </div>
      <p className="mb-4 text-[12px] leading-relaxed text-zinc-500">
        Routes straight into the P&amp;ID upload, extraction, review and result
        flow. Nothing is rebuilt here.
      </p>

      {projects.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={projectId ?? ""}
            onChange={(v) => setProjectId(Number(v))}
            ariaLabel="Project to open"
            className="h-9 min-w-[190px] flex-1"
            options={projects.map((p) => ({
              value: p.id,
              label:
                p.name +
                (p.stats.documents > 0
                  ? ` · ${p.stats.documents} drawing${p.stats.documents === 1 ? "" : "s"}`
                  : " · empty"),
            }))}
          />
          <Button
            variant="primary"
            loading={busy}
            iconRight={<IconArrowRight size={15} />}
            onClick={() => void submit()}
          >
            Open P&amp;ID
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={name}
            onChange={setName}
            ariaLabel="New project name"
            placeholder="e.g. Refinery Unit A"
            className="min-w-[190px] flex-1"
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
          />
          <Button
            variant="primary"
            loading={busy}
            icon={<IconPlus size={15} />}
            onClick={() => void submit()}
          >
            Create &amp; open
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