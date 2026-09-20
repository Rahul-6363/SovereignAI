/** Typed client for the Meshcore API.
 *
 * Browser calls are same-origin `/api/...` (proxied by next.config.mjs to the
 * FastAPI backend). Server components call the backend directly via
 * API_BASE_URL because Node's fetch cannot resolve relative URLs.
 */
import type {
  AuditEventRec,
  ConversationRec,
  DocumentRec,
  EntityDetail,
  EntityRec,
  IngestionStatus,
  MemoryGraph,
  MemoryRec,
  MessageRec,
  PageRec,
  AuditChainStatus,
  DeliverableRec,
  ProvenanceCitation,
  Project,
  RelationshipRec,
  SearchResponse,
  ToolRegistry,
  TrustStatus,
} from "./types";

const isServer = typeof window === "undefined";
const BASE = isServer ? process.env.API_BASE_URL || "http://127.0.0.1:8000" : "";

function withBase(path: string): string {
  return `${BASE}${path}`;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(withBase(path), {
    ...init,
    headers: {
      ...(init?.body && typeof init.body === "string"
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore non-JSON errors */
    }
    throw new Error(detail);
  }
  // 204 No Content (deletes) and any empty body have nothing to parse —
  // resp.json() would throw "Unexpected end of JSON input" here.
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  // ── health / trust ────────────────────────────────────────
  health: () =>
    req<{ status: string; ollama: boolean; local_only: boolean }>(
      "/api/health",
    ),
  trustStatus: () => req<TrustStatus>("/api/trust/status"),
  trustAudit: (limit = 50) =>
    req<AuditEventRec[]>(`/api/trust/audit?limit=${limit}`),

  // ── projects ──────────────────────────────────────────────
  projects: () => req<Project[]>("/api/projects"),
  createProject: (name: string, description = "") =>
    req<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  deleteProject: (id: number) =>
    req<void>(`/api/projects/${id}`, { method: "DELETE" }),
  project: (id: number) => req<Project>(`/api/projects/${id}`),
  projectGraph: (id: number) =>
    req<MemoryGraph>(`/api/projects/${id}/memory/graph`),
  search: (id: number, query: string, top_k = 10) =>
    req<SearchResponse>(`/api/projects/${id}/search`, {
      method: "POST",
      body: JSON.stringify({ query, top_k }),
    }),

  // ── documents ─────────────────────────────────────────────
  documents: () => req<DocumentRec[]>("/api/documents"),
  /** Documents of ONE project — the workspace file rail is project-scoped. */
  projectDocuments: (projectId: number) =>
    req<DocumentRec[]>(`/api/documents?project_id=${projectId}`),
  uploadDocument: (projectId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<DocumentRec>(`/api/documents/${projectId}/upload`, {
      method: "POST",
      body: form,
    });
  },
  ingestDocument: (docId: number) =>
    req<IngestionStatus>(`/api/documents/${docId}/ingest`, { method: "POST" }),
  /** Chat-composer attachment: upload then immediately queue ingestion. */
  attachDocument: async (projectId: number, file: File) => {
    const doc = await api.uploadDocument(projectId, file);
    await api.ingestDocument(doc.id);
    return doc;
  },
  ingestStatus: (docId: number) =>
    req<IngestionStatus>(`/api/documents/${docId}/status`),
  deleteDocument: (docId: number) =>
    req<void>(`/api/documents/${docId}`, { method: "DELETE" }),
  docPages: (docId: number) => req<PageRec[]>(`/api/documents/${docId}/pages`),
  docEntities: (docId: number) =>
    req<EntityRec[]>(`/api/documents/${docId}/entities`),
  docRelationships: (docId: number) =>
    req<RelationshipRec[]>(`/api/documents/${docId}/relationships`),

  // ── entities / memory ─────────────────────────────────────
  entityDetail: (entityId: number) =>
    req<EntityDetail>(`/api/documents/entities/${entityId}/detail`),
  memoryEntity: (projectId: number, tag: string) =>
    req<EntityDetail>(`/api/memory/${projectId}/entities/${tag}`),
  memories: (projectId: number) =>
    req<MemoryRec[]>(`/api/memory/${projectId}/memories`),
  memorySummary: (projectId: number) =>
    req<{ entity_count: number; tags: string[] }>(
      `/api/memory/${projectId}/summary`,
    ),

  // ── deliverables / agent ──────────────────────────────────
  deliverables: (projectId: number) =>
    req<DeliverableRec[]>(`/api/projects/${projectId}/deliverables`),
  deliverableProvenance: (projectId: number, filename: string) =>
    req<{ title: string; citations: ProvenanceCitation[] }>(
      `/api/projects/${projectId}/deliverables/${encodeURIComponent(filename)}/provenance`,
    ),
  tools: () => req<ToolRegistry>("/api/tools"),
  verifyAudit: () => req<AuditChainStatus>("/api/trust/audit/verify"),

  // ── conversations ─────────────────────────────────────────
  conversations: () =>
    req<ConversationRec[]>("/api/conversations"),
  projectConversations: (projectId: number) =>
    req<ConversationRec[]>(`/api/projects/${projectId}/conversations`),
  conversation: (conversationId: number) =>
    req<ConversationRec>(`/api/conversations/${conversationId}`),
  messages: (conversationId: number) =>
    req<MessageRec[]>(`/api/conversations/${conversationId}/messages`),
  createConversation: (projectId: number, title = "New chat") =>
    req<ConversationRec>(`/api/projects/${projectId}/conversations`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  renameConversation: (conversationId: number, title: string) =>
    req<ConversationRec>(`/api/conversations/${conversationId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (conversationId: number) =>
    req<void>(`/api/conversations/${conversationId}`, { method: "DELETE" }),
};
