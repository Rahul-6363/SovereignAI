import Link from "next/link";
import { api } from "@/lib/api";
import ProjectCard from "@/components/ProjectCard";
import NewProjectForm from "@/components/NewProjectForm";

export const dynamic = "force-dynamic";

/** Project management — create, list and delete workspaces. */
export default async function ProjectsPage() {
  let projects: Awaited<ReturnType<typeof api.projects>> = [];
  let offline = false;
  try {
    projects = await api.projects();
  } catch {
    offline = true;
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <div className="mb-8">
        <Link
          href="/"
          className="text-xs text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
        >
          ← Meshcore
        </Link>
        <h1 className="mb-2 mt-3 text-2xl font-semibold text-zinc-100">
          Projects
        </h1>
        <p className="text-sm leading-relaxed text-zinc-400">
          A project is the shared session context between the Meshcore workspace
          and the P&amp;ID capability — drawings, extracted plant memory, chats
          and deliverables all live inside one.
        </p>
      </div>

      <div className="mb-6 flex flex-col items-start gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
          {projects.length > 0 ? "Your projects" : "Create your first project"}
        </h2>
        <NewProjectForm />
      </div>

      <ul className="space-y-2">
        {projects.map((p) => (
          <ProjectCard key={p.id} project={p} />
        ))}
        {projects.length === 0 && (
          <li className="rounded-xl border border-ink-700 bg-ink-850 p-5 text-sm text-zinc-400">
            <p className="mb-2">
              No projects yet. Create one above or run the demo seed:
            </p>
            <code className="rounded bg-ink-700 px-2 py-1 font-mono text-xs text-amber-300">
              python scripts/seed_demo.py
            </code>
          </li>
        )}
      </ul>

      {offline && (
        <div className="mt-6 rounded-xl border border-rose-900/50 bg-rose-950/30 p-4 text-sm text-rose-300">
          API is unreachable. Start it with{" "}
          <code className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-xs">
            python -m uvicorn app.main:app --reload
          </code>{" "}
          in <code className="font-mono text-xs">apps/api</code>.
        </div>
      )}
    </main>
  );
}