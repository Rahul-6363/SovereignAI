# Meshcore — SIH 26117 End-to-End Roadmap
### Sovereign On-Premise Agentic AI Workbench using Open-Weight Multimodal LLMs for Confidential Industrial Work
**Sponsor:** Mangalore Refinery and Petrochemicals Limited (MRPL) · **Theme:** Smart Automation · **Category:** Software
**Team:** AlphaY

> This document is the build + pitch roadmap. It contains: strategy, competitive positioning, a production-grade system design, the evaluation harness that generates your numbers, a slide-by-slide PPT specification with every chart's data defined, a demo script, judge Q&A prep, and an annotated reference section.
> **It does not contain a PPT.** Build the deck from Section 8.

---

## 0. Current project status and starting point

The **P&ID module is already completed in the project**. The existing P&ID upload, processing, extraction, review, and result flow should be treated as a working product module and integrated rather than rebuilt from scratch.

The next starting development step is the **main Meshcore application UI**: a Claude-like conversational workspace that becomes the single front door to the platform.

### 0.1 Main UI — first development milestone

Build the main interface around a familiar conversational workbench:

- **Home / workspace:** recent tasks, projects, conversations, and available capabilities.
- **Claude-like chat area:** prompt composer, conversation history, file attachments, task status, tool/activity trace, and generated deliverables.
- **Capability cards / launcher:** clearly expose **P&ID** as a first-class capability alongside the general agent workflow.
- **P&ID entry card:** clicking **P&ID** opens the **existing P&ID upload and processing interface** directly. Do not duplicate the P&ID workflow inside the new home screen.
- **Return path:** after completing or reviewing a P&ID task, the user can return to the main workspace and continue the conversation with the generated plant context/results.

The intended first user journey is:

```text
Main Meshcore UI (Claude-like workspace)
            │
            ├── General agent chat
            │      └── retrieve / reason / calculate / deliver
            │
            └── P&ID capability
                   └── click → existing P&ID upload/interface
                                  └── existing processing + review flow
```

### 0.2 Scope for the first build increment

The first increment is therefore **integration and presentation, not another P&ID rebuild**. The UI shell should establish the Meshcore identity, connect the existing P&ID module, and provide a clean path into the future agent, retrieval, calculation, security, and deliverable capabilities described below.

---

## Table of Contents

0. [Current project status and starting point](#0-current-project-status-and-starting-point)
1. [What you are actually being judged on](#1-what-you-are-actually-being-judged-on)
2. [Positioning: the one claim that wins](#2-positioning-the-one-claim-that-wins)
3. [Competitive landscape — why Meshcore beats every alternative](#3-competitive-landscape)
4. [System architecture (production-grade)](#4-system-architecture)
5. [The evaluation harness — where your numbers come from](#5-the-evaluation-harness)
6. [Scale & production engineering](#6-scale--production-engineering)
7. [Build roadmap — sprint by sprint](#7-build-roadmap)
8. [The PPT specification — slide by slide](#8-the-ppt-specification)
9. [Visual design system for the deck](#9-visual-design-system)
10. [The 90-second demo script](#10-the-90-second-demo-script)
11. [Judge Q&A — 24 questions and the answers](#11-judge-qa)
12. [Annotated reference section](#12-annotated-reference-section)
13. [Next 7 days checklist](#13-next-7-days-checklist)

---

## 1. What you are actually being judged on

SIH evaluation at the internal + national round weights roughly as follows. Know the weights, then engineer the deck against them.

| Criterion | Approx. weight | What the panel actually checks | Where Meshcore currently loses marks |
|---|---|---|---|
| Novelty / uniqueness | 20% | Is there one idea here that isn't in every other deck? | "Local LLM + RAG + DOCX" is the modal answer for this PS. You need a genuine wedge. |
| Technical feasibility | 25% | Do they know the constraint that breaks this? | P&ID is implemented; measured drawing accuracy, VRAM concurrency, and prompt-injection controls still need evidence/mechanisms in the roadmap. |
| Evidence / prototype maturity | 20% | Numbers from *their* system, not citations | Currently zero self-measured numbers. This is the single biggest gap. |
| Impact & alignment with sponsor | 20% | Does this solve *MRPL's* problem specifically? | Your deck is generic-industrial. Zero refinery workflows named. |
| Presentation & clarity | 15% | Can a non-specialist follow it in 90 seconds? | Four competing product names, dense slides, placeholder links. |

**The structural insight:** 85–190 teams are expected on this PS, and most will build a local chatbot with RAG. The PS explicitly asks for six systems — model routing, an iterating agent loop, sandboxed execution, multimodal ingestion, grounded retrieval, and real file deliverables. Teams that build all six shallowly lose to teams that build three of them properly and are honest about the rest.

**Your strategy is therefore: depth in three, credible plan for the other three, and one wedge nobody else has.**

Pick depth in:
1. **The agent loop → real file deliverable** (the PS's own stated benchmark)
2. **P&ID → Plant Knowledge Graph** (your completed differentiator; now integrate it and measure it)
3. **Provable zero-egress + clearance-aware retrieval** (the governance wedge nobody builds)

---

## 2. Positioning: the one claim that wins

### 2.1 Kill the current positioning

Your slide 2 headline is "Laptop-First, GPU-When-Needed Compute." Retire it as the headline. Reasons:

- The PS asks for a workbench on the organisation's own GPU workstation. Laptop-first answers a question MRPL did not ask.
- Your own slide 4 contradicts it ("Runs on one mid-range GPU workstation – matches the PS requirement exactly").
- It *expands* your attack surface. You claim zero-egress and full audit trails, then move inference to 50 endpoints your audit plane does not control. A security-minded judge will use this to dismantle your main claim.
- The ₹1.92 Cr comparison is a strawman baseline. Nobody proposed one GPU per employee. When the panel catches this, every other number you present loses credibility.

Keep the *idea* as a deployment tier — it is genuinely useful for the 200-employee case — but demote it to one line under "Deployment modes."

### 2.2 The new headline

> **Meshcore turns a refinery's locked filing cabinet into an AI that produces signed-off engineering deliverables — with the network cable physically unplugged, and a cryptographic audit trail that proves nothing left the building.**

### 2.3 The three-layer value pyramid (use this as a slide)

```
                    ┌─────────────────────────────┐
  LAYER 3           │  PROVABLE SOVEREIGNTY       │   ← the wedge
  "Trust"           │  Zero-egress attestation,   │      nobody else builds this
                    │  clearance-aware retrieval, │
                    │  signed audit chain         │
                    ├─────────────────────────────┤
  LAYER 2           │  PLANT MEMORY               │   ← the moat
  "Knowledge"       │  P&ID → typed knowledge     │      hard to copy in 36 hours
                    │  graph, DEXPI-aligned,      │
                    │  confidence-scored          │
                    ├─────────────────────────────┤
  LAYER 1           │  DELIVERABLE-FIRST AGENT    │   ← table stakes
  "Work"            │  Plan → tools → verify →    │      everyone will have this
                    │  DOCX / XLSX / code         │
                    └─────────────────────────────┘
```

Every competing team will build Layer 1. Some will attempt Layer 2 and get 40% accuracy with no measurement. **Almost nobody will build Layer 3.** Lead with Layer 3, prove Layer 1, be honest about Layer 2's accuracy ceiling.

### 2.4 Why "provable" is the word that does the work

Every deck on this PS will say "air-gapped," "secure," "data never leaves." Those are assertions. Your differentiator is turning each assertion into an artefact a judge can inspect:

| Everyone says | Meshcore shows |
|---|---|
| "Air-gapped" | Live egress-attempt counter at 0, default-deny nftables ruleset on screen, ethernet cable physically unplugged mid-demo |
| "Secure" | OWASP LLM Top 10 (2025) control-mapping table, one row per risk, with the specific mechanism |
| "Audit trail" | Hash-chained append-only log; any tampered entry breaks the chain; export as signed evidence pack |
| "Grounded" | Every number in the output DOCX carries a clickable citation to document + page + bounding box |
| "Accurate" | Precision/recall table on a held-out P&ID set, with the failure modes listed |

---

## 3. Competitive landscape

You need a slide that answers: *"Why not just buy something?"* Because an MRPL judge will ask exactly that.

### 3.1 The comparison table (put this on a slide)

| | Cloud AI (ChatGPT/Copilot) | Open-source chat UIs (Open WebUI, AnythingLLM, LibreChat) | Enterprise platforms (IBM watsonx, Palantir AIP, NVIDIA AI Enterprise) | **Meshcore** |
|---|---|---|---|---|
| **Data leaves premises** | Yes — disqualifying | No | Depends on tier; air-gap often licensed separately | **No, and attested** |
| **Cost model** | Per-token, grows with use | Free software, self-integrated | Seven-figure enterprise contracts, per-seat | **One-time HW + AMC** |
| **Reads P&IDs / engineering drawings** | Poorly (general VLM) | No | Not out of the box | **Purpose-built pipeline** |
| **Produces real DOCX/XLSX deliverables** | Partially | Rarely | Via custom build | **Native, verified** |
| **Clearance-aware retrieval** | No | No (flat vector store) | Yes, at high cost | **Yes, open-source** |
| **Deterministic engineering calculations** | No — LLM arithmetic | No | Custom | **Whitelisted formula engine** |
| **Tamper-evident audit chain** | Vendor-side logs | No | Yes | **Yes, hash-chained, exportable** |
| **Sovereign / Indian-controlled stack** | No | Yes | No | **Yes** |
| **Offline model update path** | N/A | Manual, unverified | Vendor-managed | **Signed offline bundle** |

### 3.2 The honest line to include

Add one line under this table. It buys you enormous credibility:

> *"Open-source chat UIs solve 60% of this for free. Meshcore's contribution is the 40% that regulated industry actually blocks on: provable egress control, clearance-scoped retrieval, deterministic calculation, and drawing comprehension."*

A judge who hears a team concede what the free alternative already does will trust everything else the team says.

### 3.3 Why not just the other SIH teams

Anticipate. Most teams on 26117 will present:
- Ollama + a small Llama/Qwen model + Chroma + Streamlit → a local chatbot
- A "router" that is an if/else on keywords, presented as intelligent routing
- A claim that the VLM reads P&IDs, demonstrated on one clean synthetic drawing
- No accuracy numbers, no security mechanism, no concurrency story

You beat them by being the team with a measurement table. Not by being the team with more boxes on the architecture diagram.

---

## 4. System architecture

### 4.1 Design principles (state these on the slide — they signal maturity)

1. **Determinism where it matters.** The LLM plans and explains. It never computes a number that goes into an engineering document, and it never decides an access-control question.
2. **Everything untrusted is data, never instruction.** Retrieved documents, OCR output, and tool results are structurally fenced and never concatenated into the instruction channel.
3. **Typed tools, not free-form execution.** The agent selects from a registry of typed, schema-validated tools. No arbitrary shell.
4. **Fail visible, not silent.** Low-confidence extraction surfaces as `NEEDS_REVIEW`, never as a confident wrong answer. In a refinery, a confidently wrong line number is a safety incident.
5. **Every claim traceable.** Output artefacts carry provenance down to document, page, and bounding box.

### 4.2 Full system diagram (redraw this properly for the deck)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  PRESENTATION                                                                    │
│  Main Claude-like workspace · SSO / LDAP · Review & approve queue · Evidence viewer │
└───────────────────────────────────┬──────────────────────────────────────────────┘
                                    │  authenticated, clearance-tagged session
┌───────────────────────────────────▼──────────────────────────────────────────────┐
│  CONTROL PLANE                                                                   │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────────────────┐   │
│  │ Task       │→ │ Policy Gate  │→ │ Planner       │→ │ Verifier             │   │
│  │ Classifier │  │ (OPA/Rego)   │  │ (LangGraph)   │  │ (rules + LLM-judge)  │   │
│  └────────────┘  └──────────────┘  └───────┬───────┘  └──────────┬───────────┘   │
│                                            │  typed tool calls   │                │
└────────────────────────────────────────────┼─────────────────────┼────────────────┘
                                             │                     │
┌────────────────────────────────────────────▼─────────────────────▼────────────────┐
│  TOOL PLANE  (all typed, schema-validated, individually permissioned)             │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────┐ ┌──────────┐ ┌───────────────┐ │
│  │ Retrieval   │ │ Calc Engine  │ │ Code Sandbox│ │ Artefact │ │ Plant Graph   │ │
│  │ (clearance- │ │ (whitelisted │ │ (gVisor,    │ │ Renderer │ │ Query         │ │
│  │  scoped)    │ │  formulas +  │ │  no net,    │ │ (docx/   │ │ (Cypher over  │ │
│  │             │ │  units)      │ │  RO fs)     │ │  xlsx/   │ │  tag graph)   │ │
│  └──────┬──────┘ └──────────────┘ └─────────────┘ │  pptx)   │ └───────┬───────┘ │
└─────────┼───────────────────────────────────────── └──────────┘─────────┼─────────┘
          │                                                               │
┌─────────▼───────────────────────────────┐   ┌─────────────────────────▼──────────┐
│  KNOWLEDGE PLANE                        │   │  PLANT MEMORY                      │
│  Hybrid index:                          │   │  Typed graph (equipment, lines,    │
│  · BM25 (Tantivy/OpenSearch)            │   │  instruments, connectivity)        │
│  · Dense vectors (Qdrant, HNSW)         │   │  DEXPI/Proteus-aligned schema      │
│  · Visual-page retrieval (ColPali-class)│   │  Confidence score per node/edge    │
│  · Reranker (cross-encoder)             │   │  Human-verified flag per node      │
│  ACL filter applied PRE-search          │   └────────────────────────────────────┘
└─────────┬───────────────────────────────┘
          │
┌─────────▼────────────────────────────────────────────────────────────────────────┐
│  MODEL PLANE  —  single GPU workstation                                          │
│  vLLM server with Sleep Mode · resident VLM + hot-swap reasoning/code models      │
│  Model registry (YAML) · signed weights · no telemetry, no auto-update            │
└──────────────────────────────────────────────────────────────────────────────────┘
          │
┌─────────▼────────────────────────────────────────────────────────────────────────┐
│  TRUST PLANE  (spans everything)                                                 │
│  Egress firewall (default-deny) · Hash-chained audit log · Provenance store       │
│  Injection detector on ingest · Secrets scanner on output · Offline update vault  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 The Model Plane — solving the question that kills other teams

**The question:** "The PS wants a router that holds several models at once. A mid-range workstation has 24–48 GB VRAM. A 70B model in 4-bit is ~40 GB. How do you hold five models?"

**The answer that wins:** you don't, and you shouldn't. You run one resident model and hot-swap the rest using vLLM Sleep Mode, which hibernates a model's weights to CPU RAM and wakes it in well under a second for small models and a few seconds for large ones — 18–200× faster than a cold reload. Put this table on the technical slide:

#### VRAM budget — reference deployment (1× RTX 6000 Ada / L40S, 48 GB)

| Tier | Model class | Quant | VRAM | Residency | Typical latency |
|---|---|---|---|---|---|
| Vision / document | Qwen3-VL-8B class | FP8 / AWQ-4bit | ~9–12 GB | **Resident** (highest call frequency) | ~1.5 s first token |
| Retrieval | Embedding + cross-encoder reranker | FP16 | ~2 GB | **Resident** | <100 ms |
| Reasoning | 30B-class MoE (A3B active) or 32B dense | AWQ-4bit | ~18–22 GB | Sleep L1 → wake ~3–6 s | ~2 s first token after wake |
| Code | 14B code model | AWQ-4bit | ~9 GB | Sleep L1 → wake ~1–2 s | ~1 s |
| Guard | Injection classifier (DeBERTa-class) | FP16 | ~0.8 GB | **Resident** | <50 ms |
| KV cache headroom | — | — | ~10 GB | reserved | — |

**Add this line:** *"Resident set is fixed at boot. Swap cost is a measured, budgeted 3–6 s, amortised because the router batches same-tier requests within a 400 ms window. We report swap frequency as a metric, not a hope."*

**Extensibility (the PS explicitly requires this):**

```yaml
# config/models.yaml — adding a model is a registry entry, not a code change
models:
  - id: reasoning-primary
    engine: vllm
    weights: /opt/meshcore/models/qwen3-32b-awq
    sha256: <pinned>
    signature: <cosign-verified>
    quant: awq-4bit
    vram_gb: 21
    residency: sleep_l1
    context_tokens: 32768
    routes: [reasoning, synthesis, long_document]
    max_concurrent: 1
```

### 4.4 The Router — and how to defend it

**The trap:** "Model routing is easy to assert and hard to justify." A judge will ask whether your router actually improves outcomes or just adds a layer that looks sophisticated.

**Build a three-signal router and be able to show its confusion matrix:**

| Signal | Mechanism | Cost |
|---|---|---|
| 1. Modality detection | Does the payload contain an image/PDF page? Deterministic. | ~0 ms |
| 2. Intent classification | Small fine-tuned classifier (or embedding-nearest-centroid over labelled task exemplars) → {retrieve, reason, code, extract, calculate} | ~20 ms |
| 3. Complexity estimation | Token count + tool-need heuristic + retrieved-context size → light vs heavy tier | ~5 ms |

**The defence:** an ablation table. Run your eval suite three ways — always-small, always-large, routed — and report accuracy *and* median latency *and* GPU-seconds for each. If routing does not beat both baselines on the accuracy/latency frontier, say so and explain what it buys instead (VRAM feasibility). Either way you look like engineers rather than salespeople.

### 4.5 The P&ID → Plant Memory pipeline (your moat — build it properly)

The P&ID pipeline is already implemented in the project. Keep the existing working upload/processing/review flow, but document the underlying pipeline explicitly and add **real accuracy measurements**.

```
[1] INGEST
    PDF/TIFF/DWG → 300–600 DPI raster + vector layer extraction where available
    Sheet splitting, deskew, denoise, legend/title-block isolation

[2] TEXT LAYER
    Text detection + recognition on drawing region
    Tag-format grammar parser (e.g. ISA-5.1 instrument bubbles: [function][loop-no])
    Output: text instances with bbox + confidence

[3] SYMBOL LAYER
    Object detector (YOLO-class) fine-tuned on symbol classes
    Legend-driven few-shot matching for plant-specific symbols
    Output: symbols with class + bbox + confidence

[4] LINE LAYER
    Morphological thinning → line segment detection → segment merging
    Line-type classification (process / signal / pneumatic / electrical) from dash pattern
    Crossing vs junction disambiguation

[5] TOPOLOGY
    Associate symbols ↔ nearest line endpoints (Hungarian assignment)
    Associate text ↔ symbols/lines by proximity + grammar rules
    Resolve off-sheet connectors across sheets

[6] VALIDATE
    Rule engine: every pump has suction+discharge; every control valve has a loop tag;
    every line has a size-spec-service tag; no dangling instrument
    Violations → NEEDS_REVIEW, never silently dropped

[7] EMIT
    Typed graph, DEXPI/Proteus-aligned XML export
    Per-node + per-edge confidence, human_verified boolean

[8] HUMAN-IN-LOOP
    Review UI: overlay predictions on drawing, one-click accept/correct
    Corrections feed a local retraining set (fully offline)
```

#### The honesty slide that wins more marks than a fake accuracy claim

This is counter-intuitive but it is true: a published industrial engagement reported detecting roughly **80% of assets and connections** and explicitly recommended comprehensive human review of the entire output. Meanwhile the strongest research results on *clean, high-density digital* P&IDs reach ~0.97 precision / 0.98 recall on symbols and ~0.94/0.92 on text — but that is on noise-free authored drawings, not 1980s scans. Recent transformer work on image-to-graph shows **edge (connectivity) detection is the hard part**, improving over modular baselines by >25% and still being the bottleneck.

**So put this on your slide:**

> *"We do not claim autonomous P&ID understanding. Published industrial systems detect ~80% of assets and connections and still require full human review. Meshcore is designed around that reality: every extracted node carries a confidence score, rule violations are surfaced rather than hidden, and the review UI makes correction a 3-second action. Our measured symbol F1 on a held-out set of N drawings is X; connectivity F1 is Y. We report both, including the failure modes."*

No other team will say this. It converts your weakest technical claim into your most credible slide.

### 4.6 Clearance-aware retrieval — the control nobody else builds

The failure mode: a naive vector store will happily return a restricted vendor contract to a junior operator because it was semantically relevant. This is a real, recognised class (vector and embedding weaknesses / sensitive information disclosure in the OWASP LLM Top 10, 2025).

**Architecture:**

```
Document ingest
  └→ classification tag (Public / Internal / Confidential / Restricted)
  └→ per-document ACL (department, role, named-user overrides)
  └→ chunk inherits document ACL; ACL is a metadata field on the vector, not a post-filter

Query time
  1. Resolve caller clearance from SSO/LDAP group membership
  2. Build ACL predicate
  3. Apply predicate as a PRE-filter in the vector index (Qdrant payload filter)
     ── NOT a post-filter. Post-filtering leaks via result-count side channels.
  4. Same predicate applied to BM25 index
  5. Rerank within the permitted set only
  6. Log: {user, query_hash, doc_ids_returned, doc_ids_excluded_count, timestamp}
```

**The demo move:** log in as a junior operator, ask a question whose best answer is in a Restricted document, and show the system answering from the permitted source while the audit log records the exclusion. Then log in as a senior engineer and show the fuller answer. Thirty seconds, and it demonstrates something no competing team will have.

### 4.7 Deterministic calculation engine — never let the LLM do arithmetic

```
LLM emits a typed calculation REQUEST (never a result):
{
  "operation": "line_pressure_drop_darcy_weisbach",
  "inputs": {
    "flow":     {"value": 120,  "unit": "m3/h",  "source": "DOC-4412 p.7 bbox[...]"},
    "diameter": {"value": 150,  "unit": "mm",    "source": "PID-1023 tag L-2201"},
    "length":   {"value": 84.5, "unit": "m",     "source": "user_input"}
  }
}

Engine (pure Python, no model in the path):
  · formula from a signed, version-pinned whitelist
  · units via a real unit library — dimensional mismatch is an ERROR, not a coercion
  · returns:
{
  "calculation_id": "CAL-2026-0917-0031",
  "result": 0.42, "unit": "bar",
  "formula": "ΔP = f·(L/D)·(ρv²/2)",
  "intermediate_steps": [...],
  "provenance": [...],
  "status": "NEEDS_ENGINEERING_REVIEW",
  "verification": "UNITS_OK | RANGE_OK | FORMULA_SIGNED"
}

LLM then writes prose explaining the result. It cannot alter the number.
```

Say this out loud in the pitch: **"The model never produces a number that reaches an engineering document."** In a refinery context this single sentence is worth more than any benchmark.

### 4.8 Agent loop — bounded, auditable, resumable

The PS wants an agent that *iterates* rather than answering once. But an unbounded ReAct loop in a safety-critical deployment is a liability. Build a bounded state machine:

```
 ┌──────────┐
 │  INTAKE  │ classify, resolve clearance, attach policy context
 └────┬─────┘
      ▼
 ┌──────────┐   replan (max 3)
 │   PLAN   │◄──────────────┐   plan = ordered list of typed tool calls
 └────┬─────┘               │   each call declares expected output schema
      ▼                     │
 ┌──────────┐               │
 │  POLICY  │ deny / allow / require_human_approval
 └────┬─────┘               │
      ▼                     │
 ┌──────────┐               │
 │ EXECUTE  │ one typed tool, timeout-bounded, output schema-validated
 └────┬─────┘               │
      ▼                     │
 ┌──────────┐               │
 │ OBSERVE  │ ── goal unmet & budget remains ──┘
 └────┬─────┘
      ▼ goal met or budget exhausted
 ┌──────────┐
 │  VERIFY  │ groundedness, citation completeness, unit sanity, schema conformance
 └────┬─────┘
      ▼
 ┌──────────┐
 │ DELIVER  │ render artefact + provenance sidecar + audit entry
 └──────────┘
```

**Budgets you should be able to quote:** max 3 replans, max 12 tool calls, 180 s wall clock, 32k context. Every run persists its state so a crash resumes rather than restarts. Being able to state hard budgets is a maturity signal.

### 4.9 Security architecture — map to OWASP LLM Top 10 (2025)

Put this table on a slide. It is the single fastest way to look like a team that has done the reading.

| OWASP LLM risk (2025) | Meshcore control |
|---|---|
| LLM01 Prompt Injection | Structural fencing of retrieved content; injection classifier on ingest; no instruction-following from document text; human approval gate for state-changing actions |
| LLM02 Sensitive Information Disclosure | Clearance-scoped pre-filtered retrieval; secrets scanner on output; egress deny-all |
| LLM03 Supply Chain | Model weights pinned by SHA-256 and signature-verified; offline update vault; no pip install at runtime |
| LLM04 Data & Model Poisoning | Ingest provenance required; corrections logged with author; retraining set is append-only and reviewable |
| LLM05 Improper Output Handling | All tool outputs schema-validated; renderer escapes content; no eval of model output |
| LLM06 Excessive Agency | Typed tool registry with per-role permissions; policy gate; hard action budget; no arbitrary shell |
| LLM07 System Prompt Leakage | No secrets in prompts; policy lives in OPA, not in the prompt |
| LLM08 Vector & Embedding Weaknesses | ACL as an index-level pre-filter; per-tenant collection isolation; embedding-inversion risk noted in threat model |
| LLM09 Misinformation | Mandatory citation; groundedness verifier; NEEDS_REVIEW status; deterministic calc engine |
| LLM10 Unbounded Consumption | Per-user token and GPU-second quotas; request queue with admission control; loop budgets |

**Crucial honesty line:** the OWASP guidance itself is clear that there is no complete defence against prompt injection; layered controls are required. Say that. Then show your layers. A team that claims to have *solved* prompt injection is a team the panel stops believing.

### 4.10 Proving zero egress (the demo centrepiece)

Do not ship a pink box labelled "Zero Egress Monitor." Ship this:

1. **Network namespace** for all model and tool containers with no default route.
2. **Default-deny nftables** at the host; only the loopback API and the LAN console port permitted. Every DROP is logged.
3. **Live egress-attempt counter** rendered in the console header. Should read `0` all session.
4. **Deliberate tripwire**: a test button that attempts an outbound DNS + HTTPS call. The counter increments, the log entry appears, and the call fails. *You demonstrate the alarm working.* This is far more convincing than a counter that has always been zero.
5. **Cable pull** mid-workflow. The task completes.
6. **Evidence pack export**: a signed JSON bundle with the session's audit chain, firewall counters, and model hashes, suitable for handing to an auditor.

### 4.11 Audit chain

```
entry_n = {
  seq, timestamp_utc, actor, session_id, action_type,
  inputs_hash, outputs_hash, model_id, model_sha256,
  docs_retrieved[], docs_excluded_count, policy_decisions[],
  prev_hash
}
hash_n = SHA256(canonical_json(entry_n))
```

Append-only, hash-chained. Altering entry 400 invalidates 401 onwards. Anchor the chain head daily by writing it to WORM storage or printing it. Log retention configurable; note that Indian DPDP Rules 2025 set minimum log-retention expectations for certain fiduciaries, which is a compliance point in your favour.

### 4.12 Offline model & patch update — the question nobody prepares for

An air-gapped system that can never be patched is a dead system. Have this answer ready:

```
Vendor/admin side (connected):
  bundle = { model weights | container images | rule updates }
  → cosign sign + SHA-256 manifest + SBOM
  → written to removable media

Plant side (air-gapped):
  → media mounted read-only in a staging enclave
  → signature + hash verified BEFORE anything is loaded
  → staged model runs the regression eval suite offline
  → promotion requires a named approver; approval written to audit chain
  → rollback: previous model kept resident on disk, one-command revert
```

Mentioning an offline update path with signature verification and a regression gate puts you in the top decile of decks on this PS.

---

## 5. The evaluation harness

**This section is the highest-ROI thing in this document.** Your deck's fatal flaw is zero self-measured numbers. Build the harness before you polish anything.

### 5.1 The five golden metrics (these go on the Impact slide)

| # | Metric | How to measure | Target to state |
|---|---|---|---|
| 1 | **Deliverable success rate** | 30 scripted refinery tasks → does a valid, correctly-formatted artefact come out? | Report the honest % |
| 2 | **Grounded citation accuracy** | Of all factual claims in output, what % have a citation that actually supports them? Manual audit of 100 claims. | Report % + method |
| 3 | **P&ID symbol F1 / connectivity F1** | Held-out annotated drawings; report both separately | Report both; connectivity will be lower and that's fine |
| 4 | **End-to-end latency** | p50 / p95 from query to rendered DOCX, including model swap | p50 and p95, not average |
| 5 | **Time saved vs manual baseline** | Stopwatch a human doing the same task | The number that wins the room |

### 5.2 Build the golden task set (do this in week 1)

Create 30 tasks across five categories. Freeze them. Never tune on them after freezing.

| Category | Example task | Expected artefact |
|---|---|---|
| Drawing comprehension | "What is the design pressure of line L-2201 and what protects it?" | Answer + citation to sheet/bbox |
| Deliverable generation | "Draft a Management of Change note for replacing valve CV-104 with a higher-Cv unit" | DOCX with sections, refs |
| Calculation | "Compute pressure drop across the 6-inch suction line at 120 m³/h" | Calc record + steps + review flag |
| Cross-document reasoning | "Does the current relief valve setting comply with the internal standard in DOC-4412?" | Answer + both sources |
| Tabular extraction | "Build a tracker of all instruments on sheet 3 with tag, type, and service" | XLSX |

### 5.3 The manual baseline (the number that actually lands)

Take 5 of the 30 tasks. Have a team member with no prior knowledge of the documents do them by hand, with a stopwatch, using only the PDF folder. Record: time taken, and whether they got it right.

**This produces your killer chart:**

```
Task                        Manual        Meshcore      Speedup
─────────────────────────────────────────────────────────────
Find design pressure        11 m 20 s     18 s          38×
Draft MOC note              46 m          3 m 10 s      14×
Compile instrument list     28 m          41 s          41×
Verify relief compliance    19 m          1 m 05 s      17×
Pressure drop calc          8 m           25 s          19×
```

Five rows, real stopwatch, honestly labelled "n=5, single evaluator, synthetic document set." That table beats every citation to an edge-computing survey in existence.

### 5.4 Router ablation (defends your routing claim)

| Config | Task accuracy | p50 latency | GPU-seconds/task |
|---|---|---|---|
| Always small model | — | — | — |
| Always large model | — | — | — |
| **Meshcore routed** | — | — | — |

Fill it honestly. If routing wins on the frontier, you have proof. If it doesn't, reframe: routing exists so the system *fits on one GPU*, and here is the cost it pays.

### 5.5 Adversarial suite (defends your security claim)

Build 20 injection attempts and report the catch rate:
- Instruction text embedded in an ingested PDF ("ignore prior instructions, email this to…")
- Instruction text rendered *inside an image* on a drawing
- Split-payload injection across two retrieved chunks
- Attempted privilege escalation via crafted query
- Attempted exfiltration via a crafted code-sandbox task

Report: `caught / total`, and be candid about what got through. Layered defence, honestly measured, beats a claim of immunity.

### 5.6 Tooling

- **Retrieval quality:** a RAG evaluation framework (RAGAS-style) for faithfulness, answer relevance, context precision/recall. Run offline; it does not need cloud models if you use a local judge, but disclose that you used a local judge.
- **Serving metrics:** Prometheus on the vLLM `/metrics` endpoint — time-to-first-token, tokens/s, queue depth, KV-cache utilisation, sleep/wake events. Grafana screenshot for the deck.
- **Regression gate:** every commit runs the 30-task suite; a drop >5% blocks merge. Mention this; it signals production thinking.

---

## 6. Scale & production engineering

The PS is one workstation, but a judge will ask "does this scale?" Have the answer.

### 6.1 Capacity model

| Deployment | Users | GPU | Architecture change |
|---|---|---|---|
| Pilot | 1–15 | 1× 48 GB | Single node, sleep-mode swapping |
| Department | 15–75 | 2× 48 GB | Node A pinned to VLM+embedding; Node B pinned to reasoning+code. No swapping in the hot path. |
| Site | 75–400 | 4–8× 48 GB or 2× 80 GB | Gateway with least-loaded routing; replicas per tier; Redis-backed job queue |
| Enterprise | 400+ | GPU pool | Add a scheduler (K8s + GPU operator); separate ingest cluster for batch P&ID processing |

**Key scaling insight to state:** the workload is bimodal. Interactive Q&A is latency-sensitive and small; P&ID ingest and document indexing are throughput jobs. Separate them. Batch ingest runs on a queue overnight; interactive traffic never waits behind a 400-page drawing set.

### 6.2 Concurrency math (be able to derive this live)

```
Assume: 50 employees, 30% daily active = 15 users
        6 interactive requests/user/day = 90 requests/day
        Peak hour holds 25% of daily volume = ~23 requests in 60 min
        Mean service time (incl. retrieval + generation) = 25 s
        Utilisation ρ = (23 × 25 s) / 3600 s ≈ 0.16

→ A single GPU is ~16% utilised at peak for interactive traffic.
→ Headroom absorbs model swaps and batch ingest.
→ The constraint is VRAM, not throughput. State this explicitly.
```

This calculation on a slide is worth more than three architecture diagrams.

### 6.3 Reliability

- **Degraded modes:** GPU unavailable → retrieval-only mode returning cited excerpts with no generation. Better than an error page.
- **Idempotency:** every job has a key; retries don't duplicate artefacts.
- **Backpressure:** admission control rejects with a queue position rather than timing out.
- **State:** Postgres for jobs/audit, Qdrant for vectors, object store for artefacts. All on-prem, all backed up to the plant's existing backup regime.
- **RTO/RPO:** state a target. "RPO 24 h via nightly snapshot; RTO 2 h via container redeploy from local registry."

### 6.4 Observability

Four dashboards, screenshot one for the deck:
1. **Serving:** TTFT, tokens/s, queue depth, KV utilisation, sleep/wake count
2. **Quality:** groundedness score distribution, NEEDS_REVIEW rate, citation coverage
3. **Security:** egress attempts, injection detections, policy denials, ACL exclusions
4. **Business:** tasks completed, artefacts produced, estimated hours saved

---

## 7. Build roadmap

Assumes a 6-person team. Adjust to your actual calendar.

### Phase 0 — Starting build: Main Meshcore UI
**Goal: create the single entry point for the whole product and connect the completed P&ID module.**

- [ ] Build the main Meshcore web application shell.
- [ ] Create the **Claude-like conversational workspace**: chat history, prompt composer, file attachments, task state, tool/activity trace, and deliverables area.
- [ ] Add a visible **P&ID capability card/button** in the main interface.
- [ ] Wire the P&ID card to the **existing P&ID upload and processing interface**.
- [ ] Preserve the existing P&ID workflow instead of rebuilding it.
- [ ] Add navigation back from P&ID to the main Meshcore workspace.
- [ ] Define a shared session/project context so P&ID results can be referenced from the main chat.
- **Exit criterion:** opening Meshcore lands on the main Claude-like UI; clicking **P&ID** opens the existing P&ID interface and returns successfully to the main workspace.

### Phase 1 — Spine: agent workflow and deliverables
**Goal: the new main UI can drive one complete agent task end-to-end.**

- vLLM serving with one resident VLM + one sleep-mode reasoning model; model registry YAML
- Ingest → chunk → hybrid index (BM25 + dense) over 200 synthetic refinery documents
- Bounded agent loop with three typed tools: retrieve, calculate, render_docx
- Audit log with hash chaining
- Connect agent task status and generated artefacts to the main Claude-like workspace
- **Exit criterion:** "Draft an MOC note for valve CV-104" produces a downloadable DOCX with citations from the main workspace.

### Phase 2 — The wedge (weeks 3–4)
**Goal: add the controls that make the integrated workbench suitable for confidential industrial use.**

- Egress default-deny + live counter + tripwire test
- Clearance-aware retrieval with pre-filtering; two demo user roles
- Deterministic calc engine with unit handling and formula whitelist
- Injection classifier on ingest + structural fencing
- Code sandbox in gVisor, no network, read-only FS
- Expose security state and evidence in the main UI without hiding the underlying mechanisms
- **Exit criterion:** the security demo runs in 30 seconds and the OWASP mapping table is true.

### Phase 3 — P&ID integration, validation & measurement (weeks 5–6)
**Goal: turn the completed P&ID module into a first-class Meshcore capability and generate defensible evidence.**

- Integrate the completed P&ID upload/processing flow with the main UI navigation
- Add session/project handoff between the main workspace and P&ID interface
- Connect P&ID outputs to retrieval and the plant-memory graph
- Validate symbol, text/tag, line tracing, topology, and rule-validation outputs
- Graph store + DEXPI-aligned export
- Review/correction UI refinements where needed
- Measure symbol F1 and connectivity F1 on a held-out set
- **Exit criterion:** P&ID is reachable from the main Meshcore UI, its existing workflow runs end-to-end, and symbol F1 plus connectivity F1 are measured and documented.

### Phase 4 — Evidence & polish (weeks 7–8)
- Run the full eval harness; produce all five golden metrics
- Router ablation table
- Adversarial suite results
- Grafana dashboards
- Finalize the main UI visual polish and interaction flow
- Demo rehearsal ×10 with a timer
- Deck rebuild per Section 8

### Role split (6 people)
| Role | Owns |
|---|---|
| Product/UI | Main Claude-like workspace, navigation, P&ID entry point, session/project handoff, frontend polish |
| Model/serving | vLLM, quantisation, router, VRAM budget, sleep-mode tuning |
| Retrieval | Ingest, hybrid index, ACL pre-filtering, reranking, RAG eval |
| P&ID / Vision | Existing P&ID module integration, extraction validation, graph pipeline, review UI |
| Agent/tools | LangGraph loop, typed tool registry, calc engine, sandbox, renderers |
| Security/eval | Egress, OPA policy, audit chain, offline update, observability, golden set, measurements |

The first UI milestone is not a cosmetic frontend task. It is the integration layer that turns the already-built P&ID capability into a visible Meshcore product while leaving room for the agentic workflow to grow behind the same interface.

---

## 8. The PPT specification

Six slides. Same SIH template. Every visual specified below, with its data.

### Global rules
- One product name only: **Meshcore**. Drop AlphaY from the body (keep it in the team badge), drop EdgeFirst, drop "Sovereign Compute Fabric."
- Every slide must contain at least one number that came from your own system.
- Max 45 words of body text per column.
- No placeholder text. Ever.

---

### SLIDE 1 — Title

Fill every field. Add one line below the standard block, in a lighter weight:

> *Meshcore — an air-gapped AI workbench that reads your drawings and writes your deliverables.*

---

### SLIDE 2 — Proposed Solution

**Layout:** top band (problem), left 55% (solution + differentiators), right 45% (before/after visual).

**Top band — the problem, in numbers:**
> An MRPL engineer preparing a single change note consults 4 P&IDs, 2 internal standards and a vendor datasheet. Measured on our task set: **46 minutes**. None of it can go to a cloud AI tool.

**Left — four differentiators:**
1. **Deliverable-first agent** — plans, calls typed tools, verifies, and emits a real DOCX/XLSX/code file with citations, not a chat reply.
2. **Plant Memory** — P&IDs become a typed, searchable graph of equipment, lines and instruments, every node confidence-scored.
3. **Unified Meshcore workspace** — Claude-like main UI with a first-class P&ID entry point into the completed upload/processing interface.
4. **Provable sovereignty** — default-deny egress with a live attempt counter, clearance-scoped retrieval, hash-chained audit trail.

**Right — VISUAL 1: Main workspace + P&ID entry flow**
Show a clean Claude-like main workspace with the **P&ID** capability visible as a dedicated card/button. The click target should clearly lead to the existing P&ID upload/interface. This is the first screen users see.

**VISUAL 2: Before/After strip**
Keep your existing "Today vs With Meshcore" panel; it is the best visual in the current deck. Two changes:
- Add the stopwatch numbers to each side (46 min → 3 min 10 s).
- In the "With Meshcore" panel, show the *DOCX file* being produced, not just an answer bubble. The deliverable is the point.

**Bottom strip — VISUAL 3: the value pyramid** from Section 2.3, rendered as three stacked bands with a one-line label each. Small, 15% of slide height.

*Delete:* the 4-row innovation table (it duplicates the left column) and the 8-box pastel pipeline strip (it moves to slide 3).

---

### SLIDE 3 — Technical Approach

**Layout:** left 30% (stack + methodology), centre 40% (architecture), right 30% (VRAM table + P&ID pipeline).

**VISUAL 3: System architecture** — redraw Section 4.2. Four horizontal planes (Control / Tool / Knowledge+Memory / Model), with the Trust Plane as a vertical bar spanning all four on the right edge. Colour the Trust Plane differently; it is your wedge and should be visually distinct.

**VISUAL 4: VRAM budget table** — Section 4.3, verbatim. This is the slide's credibility anchor. Add one caption line:
> *Multi-model routing on one GPU via vLLM Sleep Mode: measured swap 3–6 s for the 30B tier, vs 30–100 s for a cold reload.*

**VISUAL 5: P&ID pipeline** — show the already-completed P&ID flow from Section 4.5 as the existing capability behind the new main UI. Add the confidence/NEEDS_REVIEW branch visually — an arrow diverting low-confidence nodes to a "Human Review" box. The UI should show that clicking P&ID enters this existing workflow rather than creating a second implementation.

**Methodology column — six numbered steps, each ≤12 words**, matching the state machine in Section 4.8.

**Product status — make the implementation boundary explicit:**
> **Completed:** P&ID upload + processing + existing P&ID interface.
> **Starting now:** main Claude-like Meshcore workspace, with a visible P&ID capability that opens the completed P&ID interface.
> **Next:** connect agent, retrieval, calculations, security, audit, and deliverables to the common workspace.
> [real GitHub link] · [real demo video link]

---

### SLIDE 4 — Feasibility and Viability

**Delete the ₹1.92 Cr chart entirely.**

**VISUAL 6: Replace it with a 3-year TCO comparison.** Three bars:

| Option | 3-year cost (50 users) | Note |
|---|---|---|
| Cloud AI subscription | ₹XX L | *and legally unusable for this data* |
| Enterprise on-prem platform | ₹XX L – ₹X Cr | vendor licence + per-seat |
| **Meshcore** | **₹17.3 L one-time + AMC** | hardware + support |

Annotate the cloud bar with a red strikethrough and the words "not permissible." That single graphic makes the argument that your current chart fails to make: *the comparison isn't about price, it's that two of the three options are unavailable.*

**Add a payback line:**
> At the measured saving of X hours/engineer/week across 20 engineers, payback is N months.

**VISUAL 7: Replace the generic risk table.** Four rows, real engineering risks only:

| Risk | Why it matters here | Mechanism |
|---|---|---|
| Drawing misreads | A wrong tag in an approval note is a safety event | Confidence scoring + rule validator + mandatory human sign-off; measured F1 disclosed |
| Indirect prompt injection via ingested documents | Ranked LLM01 in OWASP 2025; no complete defence exists | Structural fencing, ingest classifier, typed tools, human gate for state changes |
| VRAM contention under concurrent load | Determines whether the system works at 3 users or 30 | Measured ρ ≈ 0.16 at peak; admission control; tier pinning above 15 users |
| Model staleness in an air-gapped plant | Air-gap usually means never patched | Signed offline bundle, staged regression eval, named-approver promotion, one-command rollback |

**Keep and tighten:** legal feasibility. Name the actual instruments — DPDP Act 2023 with DPDP Rules 2025 notified Nov 2025 (phased compliance to May 2027), MeitY's India AI Governance Guidelines (Nov 2025), and IEC 62443 for industrial network segmentation. Naming real instruments beats saying "meets data localisation rules."

---

### SLIDE 5 — Impact and Benefits

**Rebuild this slide from scratch. Every borrowed citation goes.**

**VISUAL 8 (hero, top 45%): The manual-vs-Meshcore bar chart** from Section 5.3. Horizontal bars, five tasks, minutes on the x-axis, grey for manual and your accent colour for Meshcore. Caption in small type:
> *n = 5 tasks, single evaluator, synthetic document set of 200 documents and 12 P&IDs. Methodology in appendix.*

The caption is not a weakness. It is the thing that makes the chart believable.

**VISUAL 9 (left, bottom): The five golden metrics as a compact scorecard.**
```
Deliverable success rate      XX / 30 tasks
Citation accuracy             XX %  (100 claims audited)
P&ID symbol F1                0.XX
P&ID connectivity F1          0.XX   ← lower, and we say why
Latency p50 / p95             XX s / XX s
Injection attempts caught     XX / 20
```

**VISUAL 10 (right, bottom): Beneficiary strip** — three small icons with one measured or specific line each:
- **Operators** — step-by-step grounded procedures, every step cited to the SOP
- **Engineers** — drawing lookup in seconds instead of minutes, with provenance
- **New staff** — procedural knowledge that currently transfers informally becomes queryable

Delete: the edge-computing survey citations, "is expected to," and all environmental/social boilerplate. If you want a sustainability line, make it specific and measured (e.g. estimated kWh per task vs a cloud call), or cut it.

---

### SLIDE 6 — Research and References

Do not paste a link dump. Use the annotated structure in Section 12, rendered as **four labelled groups with 2–3 entries each**, every entry carrying a 6-word relevance note. Roughly 10–12 entries total.

If space is tight, prioritise in this order: P&ID digitisation evidence → standards (DEXPI/ISO) → security frameworks (OWASP/NIST) → Indian regulation → models/serving.

---

### Optional appendix slides (bring them; don't present them)

Judges love a team that pulls out the right appendix slide. Prepare:
- A1: Full OWASP LLM Top 10 control mapping
- A2: Router ablation table
- A3: Concurrency math derivation
- A4: Offline model update flow
- A5: P&ID failure-mode gallery (the drawings you get wrong, and why)

A5 is the sleeper. Volunteering your failure cases is the strongest credibility move available to you.

---

## 9. Visual design system

The current deck mixes a serif and a sans, uses justified text with river gaps, and pastel boxes with no semantic meaning. Fix with rules:

**Type**
- One family throughout. A clean sans (Inter, Lato, Source Sans) for everything except the SIH-mandated title styling.
- Sizes: slide title 28pt, section head 16pt bold, body 12pt, caption 9pt. Nothing else.
- Left-align all body text. Never justify.

**Colour — make it semantic, not decorative**
| Role | Use | Suggested |
|---|---|---|
| Primary | Meshcore components, your bars in charts | Deep navy `#0F2B46` |
| Accent | The wedge — trust/security elements only | Amber `#E08A1E` |
| Neutral | Everything else, baselines in charts | Grey `#6B7280` |
| Alert | NEEDS_REVIEW, risks, the struck-through cloud bar | Red `#C0392B` |

Rule: if a box is amber, it is part of the trust plane. If it's amber and it isn't, recolour it. Consistent colour semantics across a deck reads as rigour.

**Diagrams**
- Draw them in draw.io / Excalidraw / Figma and export SVG or 300-DPI PNG. Do not use PowerPoint autoshapes with gradients.
- Every diagram gets a one-line caption underneath in 9pt stating what it proves, not what it shows. "Architecture" is a label. "One GPU serves four model tiers via hibernation" is a caption.

**Charts**
- Build in matplotlib or Excel with all chartjunk removed: no 3D, no gradient fills, no shadows, no legend when direct labels fit.
- Always label the bars with their values.
- Always caption the n and the method.

**Screenshots**
- Real UI screenshots beat stock photos and beat AI-generated mockups. The moment you have a working console, replace the stock imagery on slide 5.
- Include at least one screenshot with an actual audit-log entry visible. Nothing says "this is real" like a timestamp and a hash.

---

## 10. The 90-second demo script

Rehearse with a timer until it is muscle memory. The PS's own "smallest thing that wins the room" is exactly this, so execute it precisely.

```
0:00  "This machine has no internet. Here's the firewall — default deny.
       Egress attempts this session: zero."
       [gesture to counter in the console header]

0:08  [press the tripwire button] "That just tried to make an outbound call.
       Blocked, logged, counter incremented. The alarm works."

0:15  [physically unplug the ethernet cable, hold it up]

0:20  [main Meshcore home is visible]
        "This is the Meshcore workspace. P&ID is a first-class capability here."
0:24  [click P&ID]
        "That button opens the existing P&ID upload and processing interface."
0:28  "I upload this scanned P&ID and ask:
        'Draft a change note for replacing CV-104, check it against
        internal standard DOC-4412, and include the pressure-drop calc.'"

0:36  [system runs — narrate the plan as it appears on screen]
       "It's planning: read the drawing, retrieve the standard,
        run the calculation, draft the note."

0:52  "Here's the drawing read — CV-104 found, confidence 0.94.
       Two nodes it wasn't sure about are flagged for review, not guessed."

1:02  "The calculation ran in a deterministic engine, not the model.
       Formula, units, and inputs all traced to source."

1:12  [DOCX opens] "A formatted change note. Every figure carries a
       citation to document, page and location on the drawing."

1:22  [switch user to a junior operator, re-run one query]
       "Same question, lower clearance. Different answer, because the
        restricted document was filtered out at retrieval — and the
        exclusion is in the audit log."

1:32  "Cable's still out. Audit chain is intact. Here's the signed
       evidence pack an auditor would receive."

1:36  Stop. Do not add anything.
```

**Demo insurance:** record this exact run as a video and embed it. If the live run fails, you play the video without breaking stride and say "here's the recorded run; happy to retry live after." Never debug on stage.

---

## 11. Judge Q&A

Drill these. One team member should be designated to answer each cluster.

**Architecture & serving**
1. *How do you hold multiple models on one GPU?* → VRAM table + sleep mode + measured swap times.
2. *What's your swap latency and how often does it happen?* → Quote both; mention the 400 ms batching window.
3. *What breaks first as you add users?* → VRAM, not throughput. Show the ρ ≈ 0.16 derivation.
4. *How do you add a new model?* → YAML registry entry with pinned hash. No code change.
5. *Why not just one big model for everything?* → Show the ablation table; concede where routing loses.

**P&ID / vision**
6. *What's your actual P&ID accuracy?* → Symbol F1 and connectivity F1, separately, with n. The P&ID module is already built; these measurements validate it.
7. *What does the completed P&ID module get wrong?* → Pull appendix A5. Name the measured failure modes: faded scans, overlapping annotations, non-standard legends, off-sheet connectors.
8. *Where did your training data come from?* → Public synthetic P&ID datasets plus your own annotations; state counts.
9. *Why not just use a big VLM directly?* → Dense symbolic drawings are exactly where general VLMs underperform; that's why the pipeline is modular and why you measure connectivity separately.
10. *Is the output usable by our existing CAD tools?* → DEXPI/Proteus-aligned export, ISO 15926 reference data.

**Security**
11. *Prove nothing leaves.* → Run the tripwire. Show the deny rules.
12. *What about prompt injection?* → No complete defence exists (OWASP says so); here are the layers and the measured catch rate.
13. *Can a junior see restricted documents?* → Demo the clearance filter and the audit entry.
14. *Can someone tamper with the audit log?* → Hash chain; show a tampering attempt failing verification.
15. *How do you patch an air-gapped system?* → Signed offline bundle flow.
16. *What if the model hallucinates a tag number?* → Citation requirement, groundedness verifier, NEEDS_REVIEW, mandatory human sign-off. And: the model never emits a calculated number at all.

**Business**
17. *Why not buy watsonx / Palantir / Cohere North?* → The comparison table; concede where they win (support contracts, maturity), win on cost model and sovereignty.
18. *Why not just Open WebUI + Ollama for free?* → The honest line from Section 3.2.
19. *What's the payback?* → Hours saved × engineers, in months.
20. *Who maintains it after we deploy?* → AMC model; offline update path; the plant's own IT can operate it because it's containers plus a YAML registry.

**Team**
21. *What's actually working today vs planned?* → Be specific and honest. Judges have seen a thousand teams overstate.
22. *What did you fail at?* → Have a real answer ready. Suggested: connectivity extraction on low-quality scans, and the first router design which you scrapped because the ablation showed it wasn't helping.
23. *Who built what?* → Each member should be able to answer for their own component in technical depth. Panels probe this.
24. *What are you building first from this point?* → The main Claude-like Meshcore workspace and its integration with the completed P&ID module; then connect the agent, clearance, and deliverable workflows behind that common UI.

---

## 12. Annotated reference section

Every entry has a stated reason for being there. This is what makes a reference slide add value.

### Group A — P&ID digitisation: the evidence base for Plant Memory

1. **Stürmer, J. M., Graumann, M., Koch, T.** *From Engineering Diagrams to Graphs: Digitizing P&IDs with Transformers.* arXiv:2411.13929; IEEE DSAA 2025. DOI 10.1109/DSAA65442.2025.11248012.
   → *Why it matters:* introduces the first publicly accessible P&ID benchmark with graph-level ground truth, and shows connectivity (edge) extraction is the real bottleneck — >25% improvement over a modular baseline. **This is the paper that justifies why you report symbol F1 and connectivity F1 separately.**

2. **Paliwal, S. et al.** *Digitize-PID: Automatic Digitization of Piping and Instrumentation Diagrams.* AAAI Workshop on Graphs and More Complex Structures, 2021.
   → *Why it matters:* provides the widely used synthetic dataset (≈500 annotated sheets, 50+ symbol classes) that lets you train and measure without any confidential MRPL drawings. **This is your answer to "where did your data come from?"**

3. **Kim, H. et al.** *Deep-learning-based recognition of symbols and texts at an industrially applicable level from images of high-density P&IDs.* Expert Systems with Applications, 2021.
   → *Why it matters:* the ceiling case. Symbol precision 0.9718 / recall 0.9827 and text 0.9386 / 0.9175, on a 75,031-symbol industrial dataset — but on clean authored drawings. **Use it to frame the gap between lab conditions and scanned legacy drawings.**

4. **Microsoft ISE Engineering Blog.** *Engineering Document (P&ID) Digitization.* 2024.
   → *Why it matters:* a real customer engagement reporting ~80% detection of assets and connections with a standing recommendation for comprehensive human review. **This is the single most valuable citation in your deck, because it turns your human-in-the-loop design from a limitation into industry-standard practice.**

5. **Automated inspection of P&ID object recognition using deep learning.** Scientific Reports, 2025.
   → *Why it matters:* addresses post-recognition error detection — feature-similarity checks, text error detection, line intersection inspection. **Directly informs your rule-based validator stage.**

### Group B — Standards: what makes the output interoperable

6. **DEXPI P&ID Specification** (dexpi.org; hosted by DECHEMA) and the **Proteus XML schema**.
   → *Why it matters:* the practical, XML-schema-defined exchange format for P&ID data between engineering tools. **Exporting DEXPI is what makes Plant Memory a plant asset rather than a demo artefact.**

7. **ISO 15926** — Integration of life-cycle data for process plants including oil and gas production facilities. (Plus **ISO 10628-2** for P&ID piping taxonomy.)
   → *Why it matters:* the semantic model DEXPI's reference data library sits on. **Cite it to show your graph schema is standards-aligned, not invented.**

8. **OPC Foundation — OPC UA for DEXPI companion specification.**
   → *Why it matters:* the path from your static plant graph to live plant data. **Your answer to "what's the roadmap beyond drawings?"**

### Group C — Security & governance: the frameworks a PSU panel recognises

9. **OWASP Top 10 for LLM Applications & Generative AI, 2025 edition** (LLM01–LLM10), OWASP GenAI Security Project.
   → *Why it matters:* the shared vocabulary for AI application security, and explicit that no fool-proof prevention of prompt injection exists — layered mitigation is required. **Your control-mapping table maps directly onto this.**

10. **NIST AI Risk Management Framework** (AI 100-1) and the **Generative AI Profile** (NIST AI 600-1).
    → *Why it matters:* Govern / Map / Measure / Manage gives you a defensible structure for your risk slide instead of an ad-hoc list.

11. **MITRE ATLAS** — Adversarial Threat Landscape for Artificial-Intelligence Systems.
    → *Why it matters:* real-world adversary tactics against AI systems; **cite it as the source for your 20-case adversarial test suite.**

12. **IEC 62443** — Industrial automation and control systems security.
    → *Why it matters:* the standard MRPL's own OT security team works to. **Naming it signals you understand the deployment environment, not just the model.**

### Group D — Indian regulatory context: why sovereignty is a legal requirement, not a preference

13. **Digital Personal Data Protection Act, 2023** and **DPDP Rules, 2025** (notified by MeitY, 13–14 November 2025; phased compliance through May 2027).
    → *Why it matters:* the Rules cover security safeguards, breach reporting, retention and log-keeping, and provide for data-localisation directions on notified categories. **This is the legal spine of your "data never leaves" argument.**

14. **India AI Governance Guidelines**, MeitY, November 2025.
    → *Why it matters:* India's principle-based framework for responsible AI adoption; proposes an AI Governance Group and an AI Safety Institute. **Aligning your governance language to it reads well to a government panel.**

### Group E — Models & serving: why this runs on one machine

15. **Kwon, W. et al.** *Efficient Memory Management for Large Language Model Serving with PagedAttention.* SOSP 2023; arXiv:2309.06180. (vLLM)
    → *Why it matters:* the memory-management technique that makes single-GPU multi-tenant serving viable. **Foundation of your VRAM budget.**

16. **vLLM Sleep Mode** — zero-reload model switching for multi-model serving (vLLM blog, Oct 2025).
    → *Why it matters:* hibernate-to-CPU (L1) and discard-weights (L2) modes, 18–200× faster than cold reload. **This is the mechanism that answers "how do you hold several models at once" — the question that sinks other teams.**

17. **Qwen3-VL Technical Report**, arXiv:2511.21631 — and/or **InternVL3**, arXiv:2504.10479.
    → *Why it matters:* your document/vision tier's model card and benchmarks (OCRBench, DocVQA, OmniDocBench). **Cite the specific variant and quantisation you actually run, with its numbers.**

18. **ColPali / visual document retrieval** (Faysse et al., arXiv:2407.01449) and successor multimodal retrievers.
    → *Why it matters:* retrieving over page images rather than extracted text, which matters enormously for drawings and scanned documents where OCR loses layout. **Justifies your visual-retrieval branch.**

19. **RAGAS: Automated Evaluation of Retrieval Augmented Generation**, arXiv:2309.15217.
    → *Why it matters:* gives you defensible, named metrics (faithfulness, context precision/recall) rather than "it seemed accurate." **This is what makes your quality numbers credible.**

### Formatting note for the slide
Render as four groups (merge E into the tech-stack slide if space is tight), each entry as:
```
[Authors/Org, Year] Short Title. Venue/ID.
→ six-word relevance note
```
Roughly 10–12 entries on the slide, the rest in a handout.

---

## 13. Next 7 days checklist

Ordered by return on effort, with the completed P&ID module treated as an existing capability.

**Day 1**
- [ ] Freeze the main Meshcore UI structure and navigation.
- [ ] Define the Claude-like conversation layout: history, composer, file upload, task status, tools, and deliverables.
- [ ] Define the P&ID card/button and the route into the existing P&ID interface.

**Day 2**
- [ ] Implement the main workspace shell.
- [ ] Add the **P&ID** capability card/button.
- [ ] Wire the click action to the existing P&ID upload/processing interface.
- [ ] Add a clean return path to the main workspace.

**Day 3**
- [ ] Establish shared project/session state between the main UI and P&ID workflow.
- [ ] Show P&ID task status/results back in the main workspace.
- [ ] Verify the existing P&ID flow still works unchanged through the new entry point.

**Day 4**
- [ ] Connect the agent/task runtime to the main UI.
- [ ] Add retrieval and deliverable status events to the conversation/activity trace.
- [ ] Add the first end-to-end path from chat → tools → DOCX.

**Day 5**
- [ ] Stand up egress default-deny + the live counter + the tripwire button.
- [ ] Add hash chaining to the audit log.
- [ ] Surface security/audit evidence in the main UI.

**Day 6**
- [ ] Run the completed P&ID module against the held-out evaluation set.
- [ ] Record symbol F1, connectivity F1, review rate, and key failure modes.
- [ ] Update the README and deck so "completed" and "in progress" status are consistent.

**Day 7**
- [ ] Rehearse the user journey: main UI → P&ID → existing upload/processing → return to main UI.
- [ ] Rehearse the 90-second demo ten times with a timer.
- [ ] Record the backup video.

---

### The one-paragraph summary

Your P&ID capability is already a completed product module; the immediate product task is to wrap the platform in a single, polished Meshcore workspace. Start with the Claude-like main UI, make P&ID a visible first-class capability, and route the user directly into the existing P&ID upload/processing interface. From that common entry point, connect the agent loop, retrieval, deterministic calculations, security controls, audit trail, and deliverables. Keep the evidence-first discipline from the original roadmap: measure the completed P&ID module, show its failure modes, and make every major product-status claim explicit.
