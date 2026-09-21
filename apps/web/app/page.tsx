import { api } from "@/lib/api";
import type { ConversationRec, Project } from "@/lib/types";
import WorkspaceHome from "@/components/WorkspaceHome";

export const dynamic = "force-dynamic";

export default async function MeshcoreHomePage() {
  let projects: Project[] = [];
  let conversations: ConversationRec[] = [];
  let offline = false;
  try {
    [projects, conversations] = await Promise.all([
      api.projects(),
      api.conversations(),
    ]);
  } catch {
    offline = true;
  }

  return (
    <>
      <WorkspaceHome projects={projects} conversations={conversations} />
      {offline && (
        <div className="mx-auto max-w-5xl px-6 pb-10">
          <div className="rounded-2xl border border-rose-900/50 bg-rose-950/30 p-4 text-[13px] text-rose-300">
            API is unreachable. Start it with{" "}
            <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[11px]">
              python -m uvicorn app.main:app --reload
            </code>{" "}
            in <code className="font-mono text-xs">apps/api</code>.
          </div>
        </div>
      )}
    </>
  );
}
