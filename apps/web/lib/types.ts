/** API types mirroring apps/api/app/schemas.py (Pydantic models). */

export interface ProjectStats {
  documents: number;
  entities: number;
  relationships: number;
  memories: number;
  chunks: number;
  last_indexed_at: string | null;
}

export interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
  stats: ProjectStats;
}

export interface DocumentRec {
  id: number;
  project_id: number;
  name: string;
  mime_type: string;
  sha256: string;
  status: string;
  stage: string;
  page_count: number;
  error: string;
  created_at: string;
}

export interface PageRec {
  id: number;
  document_id: number;
  page_number: number;
  image_url: string;
  width: number;
  height: number;
}

export interface IngestionStatus {
  document_id: number;
  status: string;
  stage: string;
  progress: number;
  pages: number;
  entities: number;
  relationships: number;
  chunks?: number;
  error: string;
}

export interface EntityRec {
  id: number;
  page_id: number;
  entity_type: string;
  canonical_tag: string;
  label: string;
  raw_text: string;
  confidence: number;
  bbox: number[];
  metadata?: EntityMetadata;
}

/** What the extraction pipeline recorded about how it found this entity. */
export interface EntityMetadata {
  model?: string;
  /** Which layers read this page, e.g. "vector-text" or "vision-tiled(3x2)". */
  path?: string;
  source_layer?: string;
  /** A rule fired on this entity; it must not be shown as settled fact. */
  needs_review?: boolean;
  review_reasons?: string[];
  line_size_mm?: number | null;
  [key: string]: unknown;
}

export interface RelationshipRec {
  id: number;
  source_tag: string;
  target_tag: string;
  relationship_type: string;
  confidence: number;
  page_id: number;
}

export interface EntityDetail {
  entity: EntityRec;
  connections: RelationshipRec[];
  source_document: string;
  page_number: number;
  image_url: string;
}

export interface GraphNode {
  id: string;
  tag: string;
  type: string;
  label: string;
  confidence: number;
  page_id?: number | null;
  bbox?: number[] | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  confidence: number;
}

export interface MemoryGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  project_id: number;
}

export interface MemoryRec {
  id: number;
  memory_type: string;
  summary: string;
  importance: number;
}

export interface EvidenceSource {
  source_type: string; // graph | pid | document | chunk | memory
  entity?: string | null;
  relation?: string | null;
  target?: string | null;
  document?: string | null;
  document_id?: number | null;
  entity_id?: number | null;
  page?: number | null;
  bbox?: number[] | null;
  text?: string | null;
  confidence?: number | null;
}

export interface EvidencePacket {
  answer_context: EvidenceSource[];
  confidence: number;
  query_intent: string;
  retrieved_from?: string;
}

export interface SearchResultItem {
  rank: number;
  source_type: string;
  tag?: string | null;
  text?: string | null;
  document?: string | null;
  page?: number | null;
  bbox?: number[] | null;
  score: number;
  confidence: number;
}

export interface SearchResponse {
  query: string;
  intent: string;
  results: SearchResultItem[];
  evidence: EvidencePacket;
}

export interface Claim {
  text: string;
  confidence: number;
  evidence_ids: string[];
}

export interface AnswerSource {
  document: string;
  page: number;
  bbox?: number[] | null;
  source_type: string;
  relation?: string;
}

export interface TrustModel {
  name: string;
  installed: boolean;
  size: string;
  role: string;
}

export interface TrustStatus {
  ollama_connected: boolean;
  external_llm_calls: number;
  network_egress: string;
  documents_local: boolean;
  audit_logging: boolean;
  models: TrustModel[];
  active_model: string;
}

export interface AuditEventRec {
  id: number;
  time: string;
  session_id: string;
  user_action: string;
  model: string;
  model_version: string;
  retrieval_count: number;
  tool_name: string;
  result_status: string;
}

export interface MessageRec {
  id: number;
  conversation_id: number;
  role: string;
  content: string;
  confidence?: number | null;
  created_at: string;
  /** "chat" (grounded answer) | "agent" (bounded task that made a file). */
  kind?: string;
  /** Persisted so a reopened thread keeps its citations and its files. */
  sources?: AnswerSource[];
  claims?: Claim[];
  artifacts?: DeliverableRec[];
}

export interface ConversationRec {
  id: number;
  project_id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  /** First user turn — what the thread is recognised by in the rail. */
  preview?: string;
}

/** ── Meshcore main UI ────────────────────────────────────── */

/** Tabs of the Meshcore project workspace (README §0.1). */
export type WorkspaceView =
  | "overview"
  | "chat"
  | "pid"
  | "memory"
  | "deliverables";

/** One line of the tool/activity trace shown under an agent turn. */
export interface ActivityStep {
  id: string;
  label: string;
  detail?: string;
  status: "pending" | "active" | "done" | "failed";
  at: string; // local HH:MM:SS
  /** The tool this step runs, matched against the stream's `tool` events.
   *  Matching on the label instead meant a plan that used one tool twice
   *  advanced both of its rows on the first call. */
  tool?: string;
}

/** A generated artefact (DOCX / XLSX / code). Rendered as a download card. */
export interface DeliverableRec {
  id: string;
  name: string;
  kind: string; // docx | xlsx | code | pdf | other
  url: string;
  created_at: string;
  citations?: number;
  size_bytes?: number;
}

/** One line of a deliverable's provenance sidecar. */
export interface ProvenanceCitation {
  section?: string;
  label: string;
  document: string;
  page?: number | null;
  bbox?: number[] | null;
  source_type: string;
}

/** The agent's entire action space, plus its hard budgets (README §4.8). */
export interface ToolRegistry {
  tools: {
    name: string;
    description: string;
    schema: Record<string, string>;
    permission: string;
  }[];
  calculations: {
    operation: string;
    formula: string;
    description: string;
    required_inputs: string[];
    result_unit: string;
    reference: string;
  }[];
  budgets: {
    max_replans: number;
    max_tool_calls: number;
    wall_clock_seconds: number;
  };
}

/** Result of walking the hash-chained audit log (README §4.11). */
export interface AuditChainStatus {
  ok: boolean;
  checked: number;
  head?: string | null;
  head_seq?: number;
  broken_at?: { seq: number; reason: string } | null;
  unchained_legacy_entries?: number;
}

/** One step of a bounded agent run, as streamed over SSE. */
export interface AgentPlanStep {
  tool: string;
  why: string;
}

export interface AgentBudgetRec {
  tool_calls: number;
  max_tool_calls: number;
  replans: number;
  max_replans: number;
  elapsed_s: number;
  wall_clock_seconds: number;
}

/** Capability maturity, stated honestly (README §1, §7, §8 Slide 3). */
export type CapabilityStatus = "available" | "phase1" | "phase2" | "planned";

export interface Capability {
  id: string;
  name: string;
  blurb: string;
  status: CapabilityStatus;
  icon: string;
}

/** What the model was actually shown for one turn (`services/context.py`).
 *
 * A small local model silently drops the front of an over-long prompt, so
 * "the model did not see that source" has to be observable rather than
 * inferred from a wrong answer.
 */
export interface ContextReport {
  model: string;
  window: number;
  prompt_tokens: number;
  reserve_for_answer: number;
  history_turns_kept: number;
  history_turns_digested: number;
  evidence_kept: number;
  evidence_total: number;
  dropped: string[];
}

/** ── client-side chat model ──────────────────────────────── */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  stage?: string; // latest operational status line
  activity?: ActivityStep[]; // tool/activity trace for this turn
  evidence?: EvidencePacket;
  confidence?: number;
  claims?: Claim[];
  sources?: AnswerSource[];
  deliverables?: DeliverableRec[];
  attachments?: { name: string; kind: string }[];
  model?: string;
  intent?: string;
  /** Token budget this turn's prompt was assembled against. */
  context?: ContextReport;
  error?: string;
  /** The user pressed Stop; whatever had streamed is kept and labelled. */
  stopped?: boolean;
  /** The prompt that produced this turn, so it can be retried verbatim. */
  prompt?: string;
  done: boolean;
}
