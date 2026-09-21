import Link from "next/link";
import { api } from "@/lib/api";
import ProjectCard from "@/components/ProjectCard";
import NewProjectForm from "@/components/NewProjectForm";
import { IconChevronLeft } from "@/components/icons";

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
    <main className="mx-auto max-w-3xl px-6 py-14">
      <div className="mb-8">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-[12px] text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={13} /> Meshcore
        </Link>
        <h1 className="mb-2.5 mt-4 text-[28px] font-medium tracking-tight text-zinc-100">
          Projects
        </h1>
        <p className="max-w-xl text-[14px] leading-relaxed text-zinc-500">
          A project is the shared session context between the Meshcore workspace
          and the P&amp;ID capability — drawings, extracted plant memory, chats
          and deliverables all live inside one.
        </p>
      </div>

      <div className="mb-6 flex flex-col items-start gap-2.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500">
          {projects.length > 0 ? "Your projects" : "Create your first project"}
        </h2>
        <NewProjectForm />
      </div>

      <ul className="space-y-2">
        {projects.map((p) => (
          <ProjectCard key={p.id} project={p} />
        ))}
        {projects.length === 0 && (
          <li className="rounded-2xl border border-dashed border-ink-800 p-6 text-center">
            <p className="mb-2.5 text-[13px] text-zinc-400">
              No projects yet. Create one above, or seed the demo data:
            </p>
            <code className="rounded-lg border border-ink-800 bg-ink-950 px-2.5 py-1.5 font-mono text-[11px] text-accent-soft">
              python scripts/seed_demo.py
            </code>
          </li>
        )}
      </ul>

      {offline && (
        <div className="mt-6 rounded-2xl border border-rose-900/50 bg-rose-950/30 p-4 text-[13px] text-rose-300">
          API is unreachable. Start it with{" "}
          <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[11px]">
            python -m uvicorn app.main:app --reload
          </code>{" "}
          in <code className="font-mono text-xs">apps/api</code>.
        </div>
      )}
    </main>
  );
}