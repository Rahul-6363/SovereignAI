"use client";

import Link from "next/link";
import { useActionState, useEffect, useState } from "react";
import { Project } from "@/lib/types";
import { deleteProjectAction } from "@/actions";
import { initialActionState } from "@/lib/action-state";
import { Badge, cn } from "./ui";
import {
  IconArrowRight,
  IconFile,
  IconGraph,
  IconTrash,
} from "./icons";

export default function ProjectCard({ project }: { project: Project }) {
  const empty = project.stats.documents === 0;
  return (
    <li className="group flex items-center gap-3 rounded-2xl border border-ink-800 bg-ink-850 p-4 shadow-raised transition-colors hover:border-ink-700">
      <Link href={`/projects/${project.id}`} className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[14px] font-medium text-zinc-100">
            {project.name}
          </span>
          {empty && <Badge color="amber">empty</Badge>}
          {project.description && (
            <span className="truncate text-[12px] text-zinc-500">
              {project.description}
            </span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-zinc-600">
          <span className="inline-flex items-center gap-1.5">
            <IconFile size={12} />
            {project.stats.documents} drawings
          </span>
          <span className="inline-flex items-center gap-1.5">
            <IconGraph size={12} />
            {project.stats.entities} tags · {project.stats.relationships} links
          </span>
          <span>{new Date(project.created_at).toLocaleDateString()}</span>
        </div>
      </Link>
      <IconArrowRight
        size={15}
        className="shrink-0 text-zinc-700 transition-colors group-hover:text-accent"
      />
      <DeleteProjectButton projectName={project.name} projectId={project.id} />
    </li>
  );
}

function DeleteProjectButton({
  projectId,
  projectName,
}: {
  projectId: number;
  projectName: string;
}) {
  const [state, formAction, pending] = useActionState(
    deleteProjectAction,
    initialActionState,
  );
  // In-place confirmation rather than `window.confirm`. The native dialog is
  // OS-themed, blocks the whole tab and cannot say what "delete" costs here —
  // which for a project is every drawing, extraction, chat and artefact in it.
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    if (!asking) return;
    const t = setTimeout(() => setAsking(false), 6000);
    return () => clearTimeout(t);
  }, [asking]);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        aria-label={`Delete project ${projectName}`}
        title={`Delete ${projectName}`}
        className="grid h-8 w-8 shrink-0 place-items-center rounded-xl text-zinc-600 opacity-0 transition-all hover:bg-rose-950/40 hover:text-rose-300 focus:opacity-100 group-hover:opacity-100"
      >
        <IconTrash size={15} />
      </button>
    );
  }

  return (
    <form action={formAction} className="shrink-0">
      <input type="hidden" name="projectId" value={projectId} />
      <div className="flex items-center gap-1.5 rounded-xl border border-rose-900/60 bg-rose-950/30 px-2 py-1.5">
        <span className="max-w-[13rem] text-[11px] leading-snug text-rose-200">
          Delete <strong className="font-medium">{projectName}</strong> with all
          its drawings, chats and artefacts?
        </span>
        <button
          type="submit"
          disabled={pending}
          className={cn(
            "shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium",
            pending
              ? "bg-ink-800 text-zinc-500"
              : "bg-rose-900/70 text-rose-50 hover:bg-rose-900",
          )}
        >
          {pending ? "Deleting…" : "Delete"}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="shrink-0 rounded-md px-1.5 py-0.5 text-[11px] text-zinc-400 hover:text-zinc-100"
        >
          Cancel
        </button>
      </div>
      {state.error && (
        <p className="mt-1 max-w-[260px] text-[11px] leading-snug text-rose-400">
          {state.error}
        </p>
      )}
    </form>
  );
}
