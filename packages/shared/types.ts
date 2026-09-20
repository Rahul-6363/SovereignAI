// Shared TypeScript contracts shared between web + api.
// Mirror of packages/schemas/extraction.schema.json for the browser.

export type EntityType =
  | "equipment"
  | "instrument"
  | "valve"
  | "process_line"
  | "tag"
  | "area"
  | "plant";

export type RelationType =
  | "HAS_TAG"
  | "CONNECTED_TO"
  | "FLOWS_TO"
  | "FROM"
  | "TO"
  | "HAS_INSTRUMENT"
  | "HAS_VALVE"
  | "MENTIONED_IN"
  | "SUPPORTED_BY"
  | "HAS_FINDING"
  | "HAS_SOP";

export type BBox = [number, number, number, number];

export interface ExtractionEntity {
  type: EntityType;
  tag: string;
  label: string;
  raw_text?: string;
  bbox: BBox;
  confidence: number;
}

export interface ExtractionRelationship {
  source: string;
  relation: RelationType;
  target: string;
  confidence: number;
}

export interface ExtractionResult {
  entities: ExtractionEntity[];
  relationships: ExtractionRelationship[];
}

// ── Evidence packet ──────────────────────────────────────────
export interface EvidenceSource {
  source_type: "graph" | "pid" | "document" | "chunk" | "memory";
  entity?: string;
  relation?: string;
  target?: string;
  document?: string;
  document_id?: number;
  page?: number;
  bbox?: BBox;
  text?: string;
  confidence?: number;
}

export interface EvidencePacket {
  answer_context: EvidenceSource[];
  confidence: number;
  query_intent?: string;
  retrieved_from?: string;
}

// ── Chat SSE events ──────────────────────────────────────────
export interface ChatStatusEvent {
  stage: string;
  detail?: string;
}

export interface ChatTokenEvent {
  text: string;
}

export interface ChatDoneEvent {
  message: string;
  confidence: number;
  claims: Claim[];
  sources: Source[];
  message_id?: number;
}

export interface Claim {
  text: string;
  confidence: number;
  evidence_ids: string[];
}

export interface Source {
  document: string;
  page: number;
  bbox?: BBox;
}

// ── Graph ────────────────────────────────────────────────────
export interface GraphNode {
  id: string;
  tag: string;
  type: EntityType;
  label: string;
  confidence: number;
  page_id?: number;
  bbox?: BBox;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: RelationType;
  confidence: number;
}

export interface MemoryGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}