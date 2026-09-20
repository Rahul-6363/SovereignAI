"use client";

import Link from "next/link";
import { useActionState } from "react";
import { Project } from "@/lib/types";
import { deleteProjectAction } from "@/actions";
import { initialActionState } from "@/lib/action-state";
import { cn } from "./ui";

export default function ProjectCard({
  project,
}: {
  project: Project;
}) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-ink-700 bg-ink-850 p-4 transition-colors hover:border-accent/50">
      <Link href={`/projects/${project.id}`} className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-zinc-100">
            {project.name}
          </span>
          {project.description && (
            <span className="truncate text-xs text-zinc-500">
              {project.description}
            </span>
          )}
        </div>
        <div className="mt-0.5 font-mono text-[11px] text-zinc-500">
          {project.stats.documents} docs, {project.stats.entities} entities,{" "}
          {project.stats.relationships} links,{" "}
          {new Date(project.created_at).toLocaleDateString()}
        </div>
      </Link>
      <DeleteProjectButton projectId={project.id} projectName={project.name} />
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
  return (
    <form action={formAction} className="shrink-0">
      <input type="hidden" name="projectId" value={projectId} />
      <button
        type="submit"
        disabled={pending}
        onClick={(e) => {
          if (
            !confirm(
              `Delete "${projectName}"? All documents, entities, and chat history will be permanently removed.`,
            )
          ) {
            e.preventDefault();
          }
        }}
        className={cn(
          "rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors",
          pending
            ? "border-ink-600 text-zinc-500"
            : "border-rose-900/60 text-rose-300 hover:bg-rose-950/40",
        )}
      >
        {pending ? "Deleting…" : "Delete"}
      </button>
      {state.error && (
        <p className="mt-1 max-w-[220px] text-[11px] leading-snug text-rose-400">
          {state.error}
        </p>
      )}
    </form>
  );
}
