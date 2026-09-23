# Meshcore

### Sovereign on-premise agentic AI workbench for confidential industrial work

**SIH 26117** · Sponsor: Mangalore Refinery and Petrochemicals Limited (MRPL) · Team AlphaY

Meshcore turns a refinery's locked filing cabinet into an AI workbench that produces
engineering deliverables — with the network cable unplugged, and a hash-chained audit
trail that shows nothing left the building.

Everything runs locally: a FastAPI service, a Next.js UI, open-weight models served by
Ollama, and SQLite on disk. There are no API keys anywhere in this repository, because
there is nothing to call.

> **Companion documents**
> · [docs/STRATEGY.md](docs/STRATEGY.md) — positioning, competitive analysis, deck spec, demo script, judge Q&A
> · [docs/VERIFICATION.md](docs/VERIFICATION.md) — how to prove each layer works, check by check

---

## Table of contents

1. [What works today](#1-what-works-today)
2. [Architecture](#2-architecture)
3. [Running the project](#3-running-the-project)
4. [Configuration reference](#4-configuration-reference)
5. [API surface](#5-api-surface)
6. [Verification, evaluation and tests](#6-verification-evaluation-and-tests)
7. [Repository layout](#7-repository-layout)
8. [Roadmap — what is next](#8-roadmap--what-is-next)
9. [Fine-tuning and tuning guide](#9-fine-tuning-and-tuning-guide)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. What works today

Everything in this section is implemented and exercised by `make verify` / `make test`.
Anything not yet built is in [§8 Roadmap](#8-roadmap--what-is-next) and is not claimed here.

### 1.1 P&ID ingestion → Plant Memory

A layered extraction pipeline that picks the cheapest layer that can actually read the
drawing in front of it, and *reports which one ran* in `_meta.path`, so no sheet is
silently treated as if it were handled like every other sheet.

| Upload | Path | Typical time | Needs a model? |
|---|---|---|---|
| Born-digital PDF (AutoCAD / SmartPlant export) | `vector-text` | < 1 s | no |
| Scan, photo, PNG/JPG export | `ocr:<engine>` + `raster-geometry` | 30–60 s | no |
| Either, if extraction is still thin | `vision-tiled(NxM)` | minutes per tile | yes |
| Bundled demo sheet, `FORCE_OFFLINE_EXTRACTION=true` | `golden` | instant | no |

Layers, each a module under [apps/api/app/services/pid/](apps/api/app/services/pid/):

- **[vector_layer.py](apps/api/app/services/pid/vector_layer.py)** — exact text, exact
  bounding boxes and drawn segments read straight out of a vector PDF. No model, no OCR error.
- **[raster_layer.py](apps/api/app/services/pid/raster_layer.py)** — multi-scale OCR
  (PaddleOCR preferred, RapidOCR fallback) for scans, including the ISA two-line
  instrument-bubble reassembly that generic OCR does not do.
- **[raster_geometry.py](apps/api/app/services/pid/raster_geometry.py)** — classical
  line detection (binarise → text suppression → segment detection → collinear merge)
  so a scan yields the same `Segment` type the vector layer produces.
- **[tiling.py](apps/api/app/services/pid/tiling.py)** — overlapping tiled VLM passes.
  A 1 m sheet downsampled to ~1000 px makes 3 mm tags illegible; tiles trade model
  calls for pixels, and `merge_tiles` reconciles anything found twice on an overlap.
- **[tag_grammar.py](apps/api/app/services/pid/tag_grammar.py)** — ISA-5.1 tag parsing.
  A parsed tag carries a *type* that does not depend on the model guessing, plus a
  confidence signal, and OCR noise that merely looks tag-shaped is rejected.
- **[topology.py](apps/api/app/services/pid/topology.py)** — relationships are
  *derived from geometry*, not believed from the model: bubble-to-nearest-symbol
  association, segment endpoints touching two symbols, left-to-right flow convention,
  shared loop numbers.
- **[rules.py](apps/api/app/services/pid/rules.py)** — engineering rule validation.
  Every violation is surfaced as a `Violation` and marks the entity `NEEDS_REVIEW`;
  nothing is silently dropped, because a quietly discarded pump looks better and is worse.

The [ingestion pipeline](apps/api/app/services/ingestion.py) runs these stages with
progress the UI can display: upload → validation → PDF/image normalisation → page
rendering → extraction → strict JSON validation → entity normalisation → relationship
inference → Plant Memory write → chunk + embed → index ready.

### 1.2 Plant Memory graph

Canonical entities and edges persist in SQLite; a NetworkX graph
([graph_memory.py](apps/api/app/services/graph_memory.py)) is rebuilt at start and
after each ingest for traversal and the UI's force-directed view. Tags are canonicalised
by [entity_normalizer.py](apps/api/app/services/entity_normalizer.py) so `PT-101`,
`PT 101` and `pt101` are one node.

### 1.3 Grounded chat, four modes

[answer_generator.py](apps/api/app/services/answer_generator.py) streams SSE events
(`status` / `evidence` / `context` / `reasoning` / `token` / `done`) in four modes
defined in [packages/prompts/modes.py](packages/prompts/modes.py):

| Mode | Retrieval | Behaviour |
|---|---|---|
| `plant` | yes | Plant-specific facts must come from evidence, word for word; general engineering knowledge is kept explicitly separate |
| `general` | no | Answers from model knowledge |
| `code` | no | Coding assistant, air-gapped posture |
| `think` | yes | A visible reasoning pass, then the answer |

Retrieval is hybrid ([hybrid_retriever.py](apps/api/app/services/hybrid_retriever.py)):
keyword + vector + graph + document lookup, merged with Reciprocal Rank Fusion.
Queries are classified deterministically first by
[query_router.py](apps/api/app/services/query_router.py) into `PID_VISUAL`,
`PLANT_MEMORY`, `DOCUMENT_SEARCH` or `GENERAL_CHAT` — a rule-based router is
reproducible in a demo in a way an LLM router is not.

**Context assembly is explicit.** [context.py](apps/api/app/services/context.py) sets
`num_ctx` and fits the prompt to it locally. Left to Ollama's default, an over-long
prompt has its *front* silently dropped — which is where the system rules and the
evidence live — and the model then answers confidently from the question alone.

### 1.4 Bounded agent loop

[agent.py](apps/api/app/services/agent.py) is a state machine, not an open ReAct loop:

```
INTAKE → PLAN → POLICY → EXECUTE → OBSERVE ─┐
                  ▲                          │ goal unmet, budget remains
                  └──────────────────────────┘
                             ↓ goal met / budget spent
                        VERIFY → DELIVER
```

Hard budgets, enforced at every transition: **3 replans, 12 tool calls, 180 s wall clock.**

### 1.5 Typed tool registry

Seven tools in [tools.py](apps/api/app/services/tools.py), each with an input schema
and a permission. There is no shell, no `eval`, and no network tool — the action space
is a closed list (OWASP LLM06, Excessive Agency).

| Tool | Permission | Purpose |
|---|---|---|
| `retrieve` | read | Search plant memory and documents; returns cited evidence |
| `list_entities` | read | List extracted entities, filtered by type or page |
| `draft` | compute | Compose general content when the project holds no evidence — output is labelled UNVERIFIED |
| `calculate` | compute | One whitelisted engineering calculation |
| `render_docx` | write | Cited DOCX + provenance sidecar |
| `render_pdf` | write | Cited PDF + provenance sidecar |
| `render_xlsx` | write | Tabular deliverable (tracker, instrument list) |

### 1.6 Deterministic calculation engine

[calc_engine.py](apps/api/app/services/calc_engine.py) exists to make one claim true:
*the model never produces a number that reaches an engineering document.* The LLM may
only emit a typed calculation **request**; the arithmetic happens in pure Python against
a version-pinned whitelist.

Currently whitelisted: `fluid_velocity`, `reynolds_number`,
`line_pressure_drop_darcy_weisbach`, `static_head_pressure`, `orifice_flow`,
`pump_hydraulic_power`, `relief_valve_area_api520`.

Units are converted through an explicit table (length, mass, time, volumetric and mass
flow, pressure, density, viscosity, velocity, temperature). A dimensional mismatch is an
**ERROR, never a silent coercion** — a quietly coerced unit is how a wrong number reaches
a drawing. An operation not in the whitelist is refused outright, so the model cannot
invent a calculation.

### 1.7 Deliverables with provenance

[renderers.py](apps/api/app/services/renderers.py) emits DOCX, XLSX and PDF. The format
is inferred from the request itself (`agent.detect_format`), so "email me a PDF of the
instrument list" and "make that a spreadsheet" reach different renderers without the
user choosing one. **Every render produces two files**: the document, and a
`.provenance.json` sidecar recording which source backed each section. Nothing in this
module talks to a model, and no value is computed here.

### 1.8 Safety and prompt-injection defence

[safety.py](apps/api/app/services/safety.py), three layers for three distinct surfaces:

1. **`screen_request`** — what the user typed. Requests whose only purpose is to defeat a
   plant safety system, falsify a record, or extract the assistant's own instructions are
   refused deterministically *in code, before any model sees the text*. A 1B model asked
   politely to ignore its rules will ignore its rules.
2. **`sanitize_evidence`** — text that came out of an ingested PDF. This is the real
   injection vector: nobody types "ignore prior instructions" into the composer, but a
   contractor's drawing can carry it. Retrieved text is structurally fenced as data.
3. Tool-result fencing — results are never concatenated into the instruction channel.

### 1.9 Trust plane

- **Hash-chained audit log** ([audit.py](apps/api/app/services/audit.py)) — each entry
  carries the hash of the one before it. `GET /api/trust/audit/verify` re-walks the chain,
  so tamper-evidence is checkable rather than asserted.
- **Egress counter** — `ENABLE_EXTERNAL_NETWORK=false` is enforced by a tripwire that
  counts and blocks attempted egress; the UI's
  [EgressCounter](apps/web/components/EgressCounter.tsx) fires a real outbound attempt on
  demand and shows it being blocked.
- **Evidence pack** — `GET /api/trust/evidence-pack` exports the chain plus metrics.
- **Model transparency** — `GET /api/trust/status` reports which models are installed,
  their sizes, and which one actually answered (or `deterministic-fallback`).

### 1.10 Web workspace

Next.js 15 / React 19 / Tailwind, in [apps/web](apps/web). All browser calls are
same-origin `/api/...`, proxied to FastAPI by a rewrite in
[next.config.mjs](apps/web/next.config.mjs).

- **Home** ([WorkspaceHome](apps/web/components/WorkspaceHome.tsx)) — one conversational
  composer, capability cards with P&ID first-class, recent projects and conversations.
- **Project workspace** ([Workspace](apps/web/components/Workspace.tsx)) —
  `Sidebar | view | Inspector`, with overview / chat / upload / memory / deliverables views.
- **Chat** ([ChatPane](apps/web/components/ChatPane.tsx)) — streaming turns, mode switch,
  evidence chips, live [ActivityTrace](apps/web/components/ActivityTrace.tsx) of the
  agent's tool calls.
- **Upload** ([UploadIngest](apps/web/components/UploadIngest.tsx)) — the live ingestion
  checklist, stage by stage.
- **Plant Memory** ([MemoryPane](apps/web/components/MemoryPane.tsx)) — force-directed SVG
  graph; clicking a node highlights its bounding box on the drawing preview.
- **P&ID viewer** ([PidViewer](apps/web/components/PidViewer.tsx)) — page image with an
  SVG overlay of 0..1 fractional bounding boxes.
- **Trust drawer** ([TrustDrawer](apps/web/components/TrustDrawer.tsx)) — local-only
  guarantees, model status, audit log.

### 1.11 Offline parity

The system is usable before any model is pulled: embeddings fall back to a deterministic
hashed character n-gram space ([embeddings.py](apps/api/app/services/embeddings.py)), and
the bundled demo sheets can replay a hand-verified golden extraction. Every offline path
is covered by `make verify` without Ollama running.

---

## 2. Architecture

### 2.1 Design principles

1. **Determinism where it matters.** The LLM plans and explains. It never computes a
   number that goes into an engineering document, and it never decides an access question.
2. **Everything untrusted is data, never instruction.** Retrieved documents, OCR output
   and tool results are structurally fenced.
3. **Typed tools, not free-form execution.** A closed registry; no shell.
4. **Fail visible, not silent.** Low confidence surfaces as `NEEDS_REVIEW`. In a refinery,
   a confidently wrong line number is a safety incident.
5. **Every claim traceable.** Artefacts carry provenance to document, page and bounding box.

### 2.2 System diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ PRESENTATION — apps/web (Next.js 15, React 19, Tailwind)                      │
│ Home workspace · Chat + ActivityTrace · Upload · Memory graph · P&ID viewer   │
│ Deliverables · Trust drawer + egress counter · Inspector                      │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ same-origin /api/* → rewrite → :8000
┌───────────────────────────────▼──────────────────────────────────────────────┐
│ API — apps/api (FastAPI)                                                      │
│ routers: health · projects · documents · chat(SSE) · memory · trust ·         │
│          deliverables(agent, tools, calculate)                                │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────────┐
│ CONTROL PLANE                                                                 │
│  safety.screen_request → query_router → agent state machine → tools registry  │
│  budgets: 3 replans · 12 tool calls · 180 s                                   │
└──────┬─────────────────┬──────────────────┬───────────────┬──────────────────┘
       │                 │                  │               │
┌──────▼──────┐  ┌───────▼───────┐  ┌───────▼────────┐  ┌───▼─────────────────┐
│ RETRIEVAL   │  │ CALCULATION   │  │ RENDERING      │  │ TRUST               │
│ hybrid RRF: │  │ calc_engine   │  │ renderers      │  │ audit (hash chain)  │
│ keyword +   │  │ whitelist +   │  │ DOCX/XLSX/PDF  │  │ egress counter      │
│ vector +    │  │ unit table    │  │ + provenance   │  │ evidence pack       │
│ graph + doc │  │ (no model)    │  │ sidecar        │  │ verify endpoint     │
│ + evidence  │  └───────────────┘  └────────────────┘  └─────────────────────┘
│   _builder  │
└──────┬──────┘
       │
┌──────▼───────────────────────────────────────────────────────────────────────┐
│ KNOWLEDGE — Plant Memory                                                      │
│  graph_memory (NetworkX, rebuilt from SQLite) · entity_normalizer · confidence│
└──────▲───────────────────────────────────────────────────────────────────────┘
       │
┌──────┴───────────────────────────────────────────────────────────────────────┐
│ INGESTION — services/ingestion.py + services/pid/*                            │
│  pid_parser (PyMuPDF render / image normalise)                                │
│    → pipeline picks a layer:                                                  │
│        vector_layer ──────────── born-digital PDF, exact, no model            │
│        raster_layer + raster_geometry ── OCR + line detection, no model       │
│        tiling → vision_extractor ─────── overlapping tiled VLM, last resort   │
│        golden replay ─────────────────── bundled demo, deterministic          │
│    → tag_grammar (ISA-5.1) → topology (geometric) → rules (NEEDS_REVIEW)      │
│    → embeddings → chunks + index                                              │
└──────┬───────────────────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────────────────┐
│ MODEL PLANE — services/ollama_gateway.py (the ONLY egress point)              │
│  chat stream · embeddings · availability probe · latency metrics              │
│  context.py sets num_ctx explicitly and fits the prompt before sending        │
└──────┬───────────────────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────────────────┐
│ Ollama (host, localhost:11434) — chat · vision · embed. No other network.     │
└──────────────────────────────────────────────────────────────────────────────┘

STORAGE  data/plant_memory.db (SQLite)  ·  data/uploads  ·  data/pages
         data/indexes  ·  data/deliverables  ·  data/demo
```

### 2.3 Request flows

**Chat turn** — `POST /api/projects/{id}/chat` (SSE):

```
message → safety.screen_request → resolve/create conversation → persist user msg
  → query_router (intent) → hybrid_retriever (RRF) → evidence_builder
  → safety.sanitize_evidence → context.assemble (fits num_ctx)
  → ollama_gateway.stream → SSE: status, evidence, context, reasoning, token, done
  → persist assistant msg → audit.append
```

**Agent task** — `POST /api/projects/{id}/agent` (SSE): the state machine above, each
tool call audited, ending in a rendered artefact plus its provenance sidecar under
`data/deliverables/project-{id}/`.

**Ingest** — `POST /api/documents/{project_id}/upload` then
`POST /api/documents/{id}/ingest` (background thread; poll
`GET /api/documents/{id}/status`). The app shuts down only after an in-flight ingest
joins, so no document is left stuck on `processing`.

### 2.4 Data model

SQLite via SQLModel, in [models.py](apps/api/app/models.py):
`Project`, `Document`, `DocumentPage`, `Entity`, `Relationship`, `Chunk`, `Memory`,
`Conversation`, `Message`, `AuditEvent`.

SQLite does not enforce foreign keys here, so a crashed ingest or interrupted delete can
orphan rows invisibly — `make doctor` reports them and `make doctor-fix` clears them.

---

## 3. Running the project

### 3.1 Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | FastAPI + pipeline |
| Node.js | 18+ | Next.js 15 |
| [Ollama](https://ollama.com) | any recent | **Optional** — the system runs offline without it |
| RAM | 16 GB minimum | The default preset is CPU-only on 16 GB |

### 3.2 First run

```bash
git clone <repo> && cd SIH

cp .env.example .env          # per-machine config; .env is gitignored
make install                  # Python deps + npm install
make demo-assets              # regenerate both demo drawings (raster + vector)
make seed-demo                # demo project + golden dataset, offline-safe

make verify                   # end-to-end checks across every layer; exit 0 = healthy
```

On Windows without `make`, run the underlying commands directly:

```powershell
Copy-Item .env.example .env
python -m pip install -r apps/api/requirements.txt
cd apps/web; npm install; cd ../..
python scripts/make_demo_pid.py; python scripts/make_vector_pid.py
python scripts/seed_demo.py
python scripts/verify_e2e.py
```

### 3.3 Start the two services

Two terminals — the API and the web app:

```bash
# terminal 1 — API on :8000
make api
# → cd apps/api && python -m uvicorn app.main:app --reload --port 8000

# terminal 2 — web on :3000
make web
# → cd apps/web && npm run dev
```

Open **http://localhost:3000**. API docs are at **http://localhost:8000/docs**.

If the UI shows "API is unreachable", terminal 1 is not up.

### 3.4 Pull models (optional)

Meshcore works without Ollama — embeddings fall back to a deterministic space and the
demo sheets replay a golden extraction. Pull models when you want live inference:

```bash
make models-small    # 16 GB / Core i5, CPU-only — ≈2.8 GB total
# gemma3:1b · moondream:1.8b · nomic-embed-text

make models          # 32 GB or a GPU — noticeably better prose
# qwen2.5vl:3b · qwen3:4b · nomic-embed-text
```

Then set the matching preset in `.env` (see [§4](#4-configuration-reference)) and restart
the API. `make models-small` and the default `.env` preset are matched to each other.

### 3.5 Better OCR (optional, recommended for real scans)

PaddleOCR reads small, thin and rotated drawing text noticeably better than the ONNX
default, at the cost of a ~700 MB install. It is deliberately **not** in the light
install path, so `make install` cannot break a working machine.

```bash
make ocr-paddle      # install PaddleOCR
make ocr-which       # show which engine will actually run, and whether OpenCV is present
```

### 3.6 The demo walk-through

1. Open http://localhost:3000 — the home workspace with capability cards.
2. Click the **P&ID** card → the upload interface.
3. Upload `data/demo/pid/unit-a-pid-vector.pdf` (born-digital, `vector-text`, < 1 s) or
   `data/demo/pid/unit-a-pid.png` (raster, the OCR path).
4. Watch the ingestion checklist run stage by stage.
5. Open **Plant Memory** — click a node and its bounding box lights up on the drawing.
6. Return to chat and ask about a tag; the answer carries evidence chips.
7. Ask for a deliverable ("build a tracker of all instruments with tag, type and service")
   → an XLSX lands in **Deliverables** with a provenance sidecar.
8. Open the **Trust drawer**: models, hash-chained audit log, egress counter at 0. Fire
   the tripwire — a real outbound attempt — and watch it blocked and counted.

Or drive it headlessly:

```bash
make ingest-demo     # upload + ingest through the API
```

### 3.7 Docker (optional)

Inference stays on the host so the demo keeps zero egress; compose only hosts the API
and the web app.

```bash
docker compose up --build     # api :8000, web :3000
```

### 3.8 Command reference

| Command | What it does |
|---|---|
| `make install` | Python deps + `npm install` |
| `make api` / `make web` | Run one service |
| `make test` | 99 unit + regression tests |
| `make verify` | End-to-end checks, in-process, throwaway DB |
| `make eval` | The five golden metrics → `data/eval-report.json` |
| `make seed-demo` | Demo project + golden dataset |
| `make ingest-demo` | Upload + ingest a demo P&ID through the API |
| `make demo-assets` | Regenerate the raster + vector demo drawings |
| `make rebuild-index` | Rebuild the vector index from persisted chunks |
| `make doctor` / `make doctor-fix` | Report / clear orphaned rows |
| `make models` / `make models-small` | Pull the model preset |
| `make ocr-paddle` / `make ocr-which` | Install / inspect the OCR engine |
| `make clean` | Drop the DB, uploads, pages, indexes and `.next` |

---

## 4. Configuration reference

All configuration lives in `.env` (gitignored, per-machine) and is loaded by
[config.py](apps/api/app/config.py). Model names appear in exactly one place so model
selection is configuration, never application logic.

Nothing here is a secret — Meshcore is air-gapped by design and there are no API keys.

### 4.1 Model plane

| Variable | Default | Notes |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | The only outbound host |
| `OLLAMA_CHAT_MODEL` | `gemma3:1b` | Small preset; `qwen3:4b` on 32 GB/GPU |
| `OLLAMA_VISION_MODEL` | `qwen2.5vl:3b` | `qwen2.5vl:7b` on 32 GB/GPU |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Falls back to a deterministic space if absent |
| `OLLAMA_NUM_PREDICT` | `320` | Answer cap; structured output overrides internally |
| `VISION_NUM_PREDICT` | `2048` | Extraction JSON cap |
| `VISION_FALLBACK_MODEL` / `REASONING_FALLBACK_MODEL` | — | Dormant while escalation is off |
| `ENABLE_MODEL_ESCALATION` | `false` | Escalate to the larger model on low confidence |

### 4.2 P&ID pipeline

| Variable | Default | Notes |
|---|---|---|
| `PID_TILE_GRID` | `auto` | `auto` scales the grid with sheet size; `off` forces single-pass; `3x2` forces a grid |
| `PID_MAX_TILES` | `9` | An NxM grid is N·M model calls — this is the cost ceiling |
| `PID_USE_VECTOR_LAYER` | `true` | Prefer a born-digital PDF's own text layer |
| `PID_USE_OCR` | `true` | OCR a raster sheet before the vision model |
| `PID_MIN_ENTITIES` | `8` | Below this, the next (costlier) layer is allowed to run |
| `MESHCORE_OCR_ENGINE` | unset | `paddleocr` \| `rapidocr`; unset prefers Paddle when installed |
| `FORCE_OFFLINE_EXTRACTION` | `false` | `true` → deterministic golden replay for bundled demo sheets |

### 4.3 Trust and storage

| Variable | Default | Notes |
|---|---|---|
| `ENABLE_EXTERNAL_NETWORK` | `false` | **Leave false.** `make verify` asserts it and the egress counter must read 0 |
| `ENABLE_AUDIT_LOG` | `true` | Hash-chained audit trail |
| `DATABASE_URL` | `sqlite:///./data/plant_memory.db` | Paths are relative to the repo root |
| `UPLOAD_DIR` / `PAGE_DIR` / `INDEX_DIR` / `DEMO_DIR` / `DELIVERABLE_DIR` | `./data/*` | Created at start |
| `CORS_ORIGINS` | `localhost:3000,127.0.0.1:3000` | Comma-separated |
| `EMBED_DIM` | `384` | Fallback embedding dimensionality |

---

## 5. API surface

Base `http://localhost:8000`. Full OpenAPI at `/docs`.

### Health
| Method | Path | |
|---|---|---|
| GET | `/api/health` | status, Ollama reachability, `local_only` |
| GET | `/api/health/ollama` | connection, base URL, installed models and sizes |

### Projects
| Method | Path | |
|---|---|---|
| GET / POST | `/api/projects` | list / create |
| GET / DELETE | `/api/projects/{id}` | fetch / delete (cascades files) |
| GET | `/api/projects/{id}/memory/graph` | Plant Memory graph |
| POST | `/api/projects/{id}/search` | hybrid retrieval |

### Documents
| Method | Path | |
|---|---|---|
| POST | `/api/documents/{project_id}/upload` | upload a P&ID or document |
| POST | `/api/documents/{id}/ingest` | start the pipeline (background) |
| GET | `/api/documents/{id}/status` | stage + progress |
| GET | `/api/documents/{id}` · `/api/documents?project_id=` | fetch / list |
| GET | `/api/documents/{id}/pages` · `/entities` · `/relationships` | extraction output |
| GET | `/api/documents/entities/{id}/detail` | entity + evidence + bbox |
| DELETE | `/api/documents/{id}` | delete document and derived rows |

### Chat
| Method | Path | |
|---|---|---|
| POST | `/api/projects/{id}/chat` | **SSE** stream; body `{message, conversation_id?, mode, retrieval_top_k}` |
| GET | `/api/conversations` · `/api/projects/{id}/conversations` | list threads |
| POST | `/api/projects/{id}/conversations` | new thread |
| GET / PATCH / DELETE | `/api/conversations/{id}` | fetch / rename / delete |
| GET | `/api/conversations/{id}/messages` | transcript |

### Memory
| Method | Path | |
|---|---|---|
| GET | `/api/memory/{project_id}/graph` · `/memories` · `/summary` | graph, memories, rollup |
| GET | `/api/memory/{project_id}/entities/{tag}` | entity detail by canonical tag |

### Agent and deliverables
| Method | Path | |
|---|---|---|
| POST | `/api/projects/{id}/agent` | **SSE** bounded agent run → artefact |
| GET | `/api/tools` | the typed tool registry |
| POST | `/api/calculate` | one whitelisted calculation |
| GET | `/api/projects/{id}/deliverables` | artefacts read from disk |
| GET | `/api/projects/{id}/deliverables/{filename}` · `/provenance` | download / sidecar |

### Trust
| Method | Path | |
|---|---|---|
| GET | `/api/trust/status` | models, egress posture, audit state |
| GET | `/api/trust/audit?limit=` | audit entries |
| GET | `/api/trust/audit/verify` | re-walk the hash chain |
| GET | `/api/trust/evidence-pack` | exportable evidence bundle |
| GET | `/api/trust/metrics` | latency and counters |
| GET | `/api/pages/{page_id}/image` | rendered page image |

---

## 6. Verification, evaluation and tests

```bash
make verify        # end-to-end checks across every layer; exit 0 = healthy
make eval          # the five golden metrics, measured this run
make test          # 99 unit + regression tests
```

All three run in-process against a throwaway database in your temp directory, so they
never touch working data, need no running server, and need no network. Checks that
require a model say so and **skip rather than fail**.

`make eval` writes [data/eval-report.json](data/eval-report.json). Every number in it
comes from that run; nothing is hardcoded. The five metrics are the deliverable success
rate, grounded citation accuracy, P&ID symbol/connectivity F1, end-to-end latency
p50/p95, and the adversarial catch rate.

The report carries its own scope note — the adversarial figure measures *structural
controls* (tool registry, formula whitelist, unit checking, clearance policy) and does
not measure a model's susceptibility to persuasion. Quote it with that caveat attached.
Likewise, the F1 figures are currently measured on the bundled demo cases, not a held-out
set; see [§8.3](#83-measurement-work-still-owed).

Full check-by-check walkthrough: **[docs/VERIFICATION.md](docs/VERIFICATION.md)**.

Other useful scripts in [scripts/](scripts/): `db_doctor.py`, `rebuild_index.py`,
`ingest_pid.py`, `seed_demo.py`, `make_demo_pid.py`, `make_vector_pid.py`,
`verify_meshcore_ui.py`, `debug_sse.py`, `test_vision_small.py`.

---

## 7. Repository layout

```
SIH/
├── apps/
│   ├── api/                       FastAPI service
│   │   ├── app/
│   │   │   ├── main.py            lifespan wiring of every service
│   │   │   ├── config.py          all settings, one place
│   │   │   ├── db.py models.py schemas.py deps.py
│   │   │   ├── routers/           health projects documents chat memory trust deliverables
│   │   │   └── services/
│   │   │       ├── agent.py       bounded state machine
│   │   │       ├── tools.py       typed registry
│   │   │       ├── calc_engine.py whitelisted formulas + unit table
│   │   │       ├── renderers.py   DOCX / XLSX / PDF + provenance
│   │   │       ├── safety.py      three-layer injection defence
│   │   │       ├── audit.py       hash-chained log
│   │   │       ├── hybrid_retriever.py  RRF over keyword/vector/graph/doc
│   │   │       ├── context.py     explicit num_ctx prompt fitting
│   │   │       ├── ingestion.py   staged pipeline
│   │   │       ├── ollama_gateway.py   the only egress point
│   │   │       └── pid/           vector_layer raster_layer raster_geometry
│   │   │                          tiling tag_grammar topology rules pipeline
│   │   ├── tests/                 golden modes pipeline regressions safety unit
│   │   └── requirements.txt
│   └── web/                       Next.js 15 workspace
│       ├── app/                   / · /workspace · /projects/[id]
│       ├── components/            Workspace ChatPane MemoryPane PidViewer
│       │                          TrustDrawer EgressCounter Deliverables …
│       └── lib/                   api.ts sse.ts types.ts
├── packages/
│   ├── prompts/modes.py           the four mode prompts
│   ├── schemas/extraction.schema.json   strict extraction contract
│   └── shared/types.ts
├── scripts/                       verify_e2e · eval_harness · seed_demo · db_doctor …
├── data/                          plant_memory.db uploads pages indexes demo deliverables
├── docs/                          STRATEGY.md · VERIFICATION.md
├── Makefile · docker-compose.yml · .env.example
```

---

## 8. Roadmap — what is next

The shipped/not-shipped boundary is also stated inside the product itself, in
[ProductStatus.tsx](apps/web/components/ProductStatus.tsx), and the two must stay in
agreement — a status line nobody can trust is worse than none.

### 8.1 In progress

**Clearance-aware retrieval as an index pre-filter.** Clearance is currently carried on
the tool-invocation context (`ToolContext.clearance`, default `internal`) but is not yet
enforced at the index. The goal is that a lower clearance *cannot retrieve* restricted
content, rather than merely not being shown it — filtering after retrieval still puts the
text in the prompt. Work: a clearance column on `Chunk` and `Entity`, a pre-filter inside
`hybrid_retriever`, two demo roles, and an eval case proving a restricted chunk is absent
from the evidence packet rather than hidden in the UI.

### 8.2 Next

| Item | Why it matters |
|---|---|
| **Wider deterministic calculation coverage** | Seven formulas cover the demo; a refinery needs control-valve Cv sizing, PSV sizing beyond API 520 area, line-sizing tables and heat-exchanger duty. Each addition is a `Formula` entry plus its unit dimensions and a test |
| **Network-isolated code sandbox** | For running generated code against plant data: no network, read-only FS, gVisor or equivalent. Until it exists there is no code-execution tool, and the registry says so |
| **DEXPI-aligned export** | Makes extraction output interoperable with plant engineering tools rather than trapped in Meshcore |
| **Review / correction UI** | An engineer correcting a `NEEDS_REVIEW` entity should write that correction back to Plant Memory and have it outrank the extraction |
| **SSO / LDAP** | The presentation layer assumes an authenticated, clearance-tagged session; today there is no auth |
| **Offline signed model-update bundle** | An air-gapped deployment still needs a patch path — a signed bundle with signature verification before install |
| **vLLM serving with sleep-mode model swap** | Ollama is the right choice for a laptop demo; a single-GPU workstation serving concurrent users wants vLLM, a resident VLM and a sleep-mode reasoning model |
| **Prometheus / Grafana observability** | Time-to-first-token, tokens/s, queue depth, KV-cache utilisation, sleep/wake events |
| **Regression gate in CI** | The golden task suite on every commit; a >5% drop blocks merge |

### 8.3 Measurement work still owed

- **Held-out P&ID set.** Symbol and connectivity F1 are currently measured on the bundled
  demo cases. The number that matters is on drawings the pipeline has never seen, with the
  failure modes listed beside it.
- **Manual baseline.** Stopwatch a human doing five of the golden tasks by hand from the
  PDF folder. Report `n=5, single evaluator, synthetic document set` — the honest label is
  what makes the speedup credible.
- **Router ablation.** Always-small vs always-large vs routed, on accuracy, p50 latency and
  GPU-seconds per task. If routing loses, the reframe is that routing exists so the system
  *fits on one GPU*, and here is the cost it pays.
- **Model susceptibility.** The adversarial suite measures structural controls. It does not
  yet measure whether the model itself can be talked around.

---

## 9. Fine-tuning and tuning guide

Two distinct things live under "fine-tuning" here. Most of the accuracy available today is
in the second, and it costs nothing.

### 9.1 Tuning what already exists (do this first)

**Choose the right model preset.** The default `gemma3:1b` preset exists so the system
runs on a 16 GB CPU laptop, and it costs real quality: the small chat model paraphrases
loosely and will mislabel a line as an instrument. On 32 GB or a GPU, switch to
`qwen3:4b` + `qwen2.5vl:7b` and both the prose and the extraction improve noticeably.
This is one `.env` edit and a restart.

**Get the drawing onto a cheaper layer.** The single largest accuracy lever is *which
layer reads the sheet*, not how the model is prompted:

- A born-digital PDF through `vector-text` gives exact text and exact geometry with no
  model in the loop. If a source PDF exists, use it instead of a PNG export.
- For scans, install PaddleOCR (`make ocr-paddle`). It reads small, thin and rotated
  drawing text markedly better than the ONNX default. Confirm with `make ocr-which`, and
  check `_meta.path` in the extraction result — the engine name is part of the number.
- Keep OpenCV installed so `raster_geometry` can recover pipe runs; without it, topology
  on a scan falls back to proximity, which is guesswork.

**Tune the tiling budget.** `PID_TILE_GRID=auto` scales the grid with sheet size.
Raise `PID_MAX_TILES` for a dense A0 sheet if you can afford N·M model calls; lower it, or
set `off`, when latency matters more than recall. `PID_MIN_ENTITIES` is the threshold
below which the next, costlier layer is allowed to run — raise it to make the pipeline
more willing to escalate, lower it to keep runs fast.

**Tune retrieval.** `retrieval_top_k` on the chat request (1–30, default 10) trades recall
against how much of the small model's context the evidence consumes. With a 1B model, more
evidence is not automatically better — `context.py` fits the prompt to `num_ctx`, and past
a point that means dropping evidence you asked for.

**Tune generation caps.** `OLLAMA_NUM_PREDICT=320` keeps a small model from rambling;
raise it for long deliverables. `VISION_NUM_PREDICT` must stay large enough to hold a full
extraction JSON — truncated JSON is a failed extraction, not a short one.

### 9.2 Prompt tuning

The four mode prompts are in [packages/prompts/modes.py](packages/prompts/modes.py) and
are written for a 1B model specifically. Three rules, learned the hard way, that any edit
should respect:

1. **Keep them short.** `context.assemble` caps the system message at roughly 1,400
   characters before truncating, and truncation loses the *last* rules. Put the most
   important rule first so degradation is graceful.
2. **Frame rules as things to DO.** A small model told "never invent a tag" reliably
   invents one; the same model told "use only tags from the evidence" mostly complies.
3. **Do not make evidence a ceiling.** An earlier version said "answer ONLY from the
   evidence" and produced answers that were thin and oddly incurious. Evidence is what
   makes plant-specific claims *true*; it was never meant to bound what the assistant may
   know. The current prompt keeps the two sources separate instead of forbidding one.

Re-run `make eval` before and after any prompt change. If citation accuracy moves, the
prompt moved something real.

### 9.3 Actual model fine-tuning (not yet done)

Nothing in this repository fine-tunes model weights today, and the roadmap deliberately
ranks it below the levers above — a LoRA on a 3B VLM will not beat reading a vector PDF's
own text layer. When it becomes worth doing, the ordering is:

1. **Vision adapter for P&ID symbols.** A LoRA on the vision model over annotated refinery
   sheets, targeting the symbol classes the ISA grammar cannot recover from text alone.
   This is the case with the clearest headroom, because symbols are exactly what OCR
   cannot read. It requires a labelled set well beyond the current demo cases.
2. **Embedding adaptation.** `nomic-embed-text` is general-purpose; industrial tags and
   service descriptions are a narrow domain. A contrastive adapter over plant vocabulary
   would improve the vector arm of the RRF merge.
3. **Instruction tuning for deliverable shapes.** MOC notes, instrument trackers and
   compliance memos have house formats. Tuning for structure would reduce how much the
   renderers have to repair.

All three must stay compatible with the air-gap: training runs on the same on-premise
hardware, adapters ship in the signed offline bundle described in §8.2, and
`ENABLE_EXTERNAL_NETWORK` stays `false` throughout. A fine-tuned model that required a
cloud round trip would forfeit the claim the whole product rests on.

**Evaluate before adopting.** Freeze the golden task set, run `make eval` against the base
model, then against the adapter, and publish both. An adapter that improves symbol F1
while degrading citation accuracy is not an improvement.

---

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| UI says "API is unreachable" | The API is not running. `make api` in a second terminal |
| Extraction returns almost nothing from a scan | OCR is not installed, or OpenCV is missing. `make ocr-which`, then `make ocr-paddle` |
| Extraction takes minutes | It fell through to `vision-tiled`. Check `_meta.path`; supply the born-digital PDF, or install OCR |
| A document is stuck on `processing` | An ingest crashed. `make doctor`, then `make doctor-fix` |
| Answers ignore the evidence | The prompt exceeded `num_ctx` and the front was dropped. Lower `retrieval_top_k`, or read the `context` SSE event for the budget the prompt was assembled against |
| Vision extraction returns invalid JSON | `VISION_NUM_PREDICT` is too low — the JSON was truncated mid-object |
| `next build` dies at "Collecting page data" | A dev server is using `.next`. Set `NEXT_DIST_DIR` to build alongside it |
| Answers are vague or mislabel entity types | The `gemma3:1b` preset. Switch to the `qwen3:4b` preset in `.env` |
| Ollama not installed | Expected to work — embeddings fall back deterministically and demo sheets replay golden extraction |

---

## Licence and provenance

Built for Smart India Hackathon 2026, problem statement **26117**, sponsored by MRPL.
Open-weight models only; no proprietary API is called at any point.
