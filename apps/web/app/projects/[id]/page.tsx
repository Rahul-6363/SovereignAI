import { api } from "@/lib/api";
import Workspace from "@/components/Workspace";
import type { WorkspaceView } from "@/lib/types";

export const dynamic = "force-dynamic";

const VIEWS: WorkspaceView[] = [
  "overview",
  "chat",
  "pid",
  "memory",
  "deliverables",
];

export default async function ProjectPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    view?: string;
    q?: string;
    conversation?: string;
    from?: string;
  }>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const projectId = Number(id);
  if (!Number.isFinite(projectId)) {
    return (
      <main className="p-10 text-sm text-zinc-400">Invalid project id.</main>
    );
  }

  // Deep links are how the main Meshcore workspace reaches a capability:
  //   ?view=pid          → the existing P&ID upload/processing interface
  //   ?view=chat&q=…     → handoff from the home composer
  //   ?conversation=…    → shared session context / conversation history
  const view: WorkspaceView = VIEWS.includes(sp.view as WorkspaceView)
    ? (sp.view as WorkspaceView)
    : "chat";
  const conversationId = sp.conversation ? Number(sp.conversation) : null;

  try {
    await api.project(projectId);
    return (
      <Workspace
        projectId={projectId}
        initialView={view}
        initialPrompt={sp.q ?? ""}
        initialConversationId={
          Number.isFinite(conversationId) ? conversationId : null
        }
        fromPid={sp.from === "pid"}
      />
    );
  } catch {
    return (
      <main className="p-10">
        <h1 className="mb-2 text-lg text-zinc-200">Project not found</h1>
        <a
          href="/"
          className="text-sm text-accent underline-offset-2 hover:underline"
        >
          ← Back to Meshcore
        </a>
      </main>
    );
  }
}
