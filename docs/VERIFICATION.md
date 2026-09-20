# Verifying Meshcore end to end

*Written for: the Meshcore team (and anyone demoing or judging the build).*

This is the practical answer to **"is it actually working?"** — what to run, in
what order, and what each result proves. Nothing here needs the web UI open,
and nothing needs a network connection.

---

## TL;DR — three commands

```bash
make verify        # 53 checks across every layer; exit 0 = healthy
make eval          # the five golden metrics, measured this run
make test          # 69 unit + regression tests
```

If all three are green, the system works. Everything below explains what that
means and how to check any single piece by hand.

---

## 0. One-time setup

```bash
make install             # Python deps + npm install
make demo-assets         # regenerate both demo drawings (raster + vector)
```

`make demo-assets` produces two deliberately different sheets:

| File | Kind | What it tests |
|---|---|---|
| `data/demo/pid/unit-a-pid.png` | raster | the scanned-drawing path (vision model or golden replay) |
| `data/demo/pid/unit-a-pid-vector.pdf` | born-digital | the vector path — exact text + geometry, no model |

Ollama is **optional**. Every offline path is verified without it; the checks
that need a model say so and skip rather than fail.

### Which path reads your drawing

The pipeline picks the cheapest layer that works, and reports which one ran in
`_meta.path`:

| Your upload | Path taken | Typical time | Needs a model? |
|---|---|---|---|
| Born-digital PDF (AutoCAD / SmartPlant export) | `vector-text` | < 1 s | no |
| Scan, photo, PNG/JPG export | `ocr:<engine>` + `raster-geometry` | 30–60 s | no |
| Either, if still thin | `vision-tiled(NxM)` | minutes per tile | yes |

### Choosing an OCR engine

`_meta.path` names the engine that ran (`ocr:paddleocr`, `ocr:rapidocr`),
because the two do not score the same on a dense sheet and a recall figure
without the engine beside it does not mean anything.

| Engine | Install | When to use |
|---|---|---|
| **RapidOCR** (default) | in `requirements.txt`, ONNX, ~80 MB | the offline default; no PyTorch, no Paddle runtime |
| **PaddleOCR** | `make ocr-paddle` (~700 MB) | better on small, thin and rotated drawing text |

PaddleOCR is deliberately **not** in `requirements.txt`: `make install` has to
stay light and must not break a working machine. Both PaddleOCR 2.x and 3.x
are supported. Force a choice with `MESHCORE_OCR_ENGINE=paddleocr|rapidocr`;
a broken explicit choice still falls back rather than dropping the sheet to
the vision model.

```bash
make ocr-paddle     # install PaddleOCR
make ocr-which      # which engine will actually run, and is OpenCV present
```

**If you have the PDF, upload the PDF.** A born-digital sheet is read exactly
and instantly; the same drawing flattened to PNG has to be read back out of
pixels. That single choice is worth more than any other tuning.

---

## 1. `make verify` — the full sweep

Runs `scripts/verify_e2e.py` in-process against a throwaway database in your
temp directory. **It never touches `data/plant_memory.db`.**

It prints a `[PASS]`/`[FAIL]` line per check, grouped by layer, so a failure
names the layer that broke instead of leaving you to bisect it:

| § | Layer | Proves |
|---|---|---|
| 1 | Service + runtime | API up, `local_only` true, Ollama status |
| 2 | Project lifecycle | create, read back |
| 3 | **P&ID extraction** | symbol F1, connectivity F1, ISA-5.1 typing, rules ran, zero model calls on a vector sheet |
| 4 | Upload + ingestion | upload → render → extract → graph → index → `ready`; page image serves |
| 5 | Plant Memory graph | nodes and edges exist |
| 6 | Hybrid retrieval | hits returned, intent classified, scores numeric |
| 7 | Grounded chat | SSE streams, evidence attached, confidence reported, **multi-turn follow-up resolves** |
| 8 | Calculation engine | correct number, working shown, review flag, **3/3 invalid calls refused** |
| 9 | Bounded agent | plan → policy → typed tools → verify → artefact with citations, budgets respected, path traversal refused, **operator clearance denied write** |
| 10 | Tabular deliverable | XLSX tracker produced |
| 11 | Trust + audit | egress blocked, external LLM calls = 0, **chain detects tampering at the right entry and re-verifies after restore** |
| 12 | Cleanup | project deletes with no residue |

Flags: `--quick` skips ingestion (fastest smoke test), `--keep` leaves the
fixture project behind for inspection.

**Expected result:** `RESULT: 53/53 checks passed`.

---

## 2. `make eval` — the five golden metrics

Runs `scripts/eval_harness.py`. Every number printed is measured by that run;
nothing is hardcoded. Writes `data/eval-report.json` for the deck.

Current measured figures on the bundled set:

| # | Metric | Result |
|---|---|---|
| 1 | Deliverable success rate | **10/10 = 100%** across MOC / tracker / calculation / answer tasks |
| 2 | Grounded citation accuracy | **100%** of 55 citations resolve to a real source |
| 3 | P&ID symbol F1 | **1.000** (19/19) on the born-digital sheet |
| 3 | P&ID connectivity F1 | **0.968** (P=1.000, R=0.938) |
| 4 | End-to-end latency | **p50 ≈ 80 ms, p95 ≈ 130 ms** (offline paths) |
| 5 | Structural controls | **13/13** behaved correctly |

Run one section at a time with `--only pid|agent|adversarial`.

### Reading these honestly

- **Connectivity F1 sits below symbol F1.** That is the published pattern in
  the literature and it is reported, not hidden. The single missed link
  (`L-104 → E-101`) is a bypass line the drawing does not actually connect —
  the extractor is right and the ground truth is optimistic.
- **Symbol F1 = 1.000 applies to the born-digital path.** A raster sheet goes
  through OCR and scores lower; that is a different number and should be
  quoted as one. Measured on a real MRPL-style PNG (1536x1024, 22 taggable
  items): **20 entities recovered in ~40 s**, with 13 relationships. Before
  the OCR layer existed the same sheet took **15 minutes and returned one
  entity**, so quote the raster figure as ~0.9 recall, not as 1.000.
- **Metric 5 measures structural controls only** — the tool whitelist, formula
  whitelist, unit checking and clearance policy. It does *not* measure whether
  a language model can be talked into saying something unwise. Say that out
  loud; a team claiming to have solved prompt injection is a team the panel
  stops believing.
- Latency figures are for the offline paths. With a live vision model on CPU,
  ingestion is minutes per page, not milliseconds. Quote both.

---

## 3. `make test` — unit and regression tests

69 tests. `tests/test_regressions.py` pins every bug found in review so a
refactor cannot quietly reintroduce it; `tests/test_pipeline.py` pins the
behaviours the product's claims rest on.

Tests run against a temp database (`tests/conftest.py`), so a test run never
pollutes your working data.

---

## 4. Checking pieces by hand

### Which layers ran, and why it took as long as it did

```bash
python -c "
import asyncio, sys; sys.path.insert(0,'apps/api')
from PIL import Image
from app.services.pid import pipeline, raster_layer, raster_geometry
print('OCR   available:', raster_layer.available())
print('OpenCV available:', raster_geometry.available())
img = Image.open('your-drawing.png')
out = asyncio.run(pipeline.extract_page(img, vision_call=None))
print('path:', out['_meta']['path'])
print(len(out['entities']), 'entities,', len(out['relationships']), 'links')"
```

If `OCR available` is False, every raster upload falls through to the vision
model — that is the 15-minutes-for-one-entity case. Install it.

### The P&ID pipeline on your own drawing

```bash
python - <<'PY'
import asyncio, sys; sys.path.insert(0, "apps/api")
import pymupdf
from PIL import Image
from app.services.pid import pipeline

path = "path/to/your.pdf"
doc = pymupdf.open(path)
page = doc[0]
pix = page.get_pixmap(dpi=150)
img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

out = asyncio.run(pipeline.extract_page(img, pdf_page=page, vision_call=None))
print("path :", out["_meta"]["path"])
print("found:", len(out["entities"]), "entities,", len(out["relationships"]), "links")
for e in out["entities"][:15]:
    flag = " NEEDS_REVIEW" if e.get("needs_review") else ""
    print(f"  {e['tag']:12} {e['type']:13} {e['confidence']:.2f}{flag}")
for v in out["_meta"]["validation"]["violations"][:8]:
    print(f"  [{v['severity']}] {v['rule']}: {v['message']}")
PY
```

If `path` reads `vector-text`, the sheet was born-digital and was read exactly.
If it reads `none`, the PDF is a scan — start Ollama and pull a vision model.

### The calculation engine

```bash
python -c "
import sys; sys.path.insert(0,'apps/api')
from app.services.calc_engine import calculate
r = calculate('line_pressure_drop_darcy_weisbach', {
  'flow':{'value':120,'unit':'m3/h'}, 'diameter':{'value':150,'unit':'mm'},
  'length':{'value':84.5,'unit':'m'}, 'density':{'value':850,'unit':'kg/m3'},
  'viscosity':{'value':3.2,'unit':'cp'}}, output_unit='bar')
print(r.result, r.unit, r.status)
[print(' ', s) for s in r.intermediate_steps]"
```

### The audit chain

```bash
curl -s localhost:8000/api/trust/audit/verify | python -m json.tool
curl -s localhost:8000/api/trust/evidence-pack > evidence-pack.json
```

`ok: true` means no entry has been altered. Edit any row in `audit_events` and
re-run: it reports the exact `seq` that broke.

### Database integrity

```bash
make doctor            # report rows orphaned by a crashed ingest
make doctor-fix        # delete them
```

SQLite does not enforce foreign keys, so these stay invisible otherwise.

---

## 4a. The chat workspace

One input handles both jobs. A question streams a grounded answer; a request
for a file runs the bounded agent and the document appears in the thread,
downloadable. The composer says which of the two it is about to do before you
press send, and a **Build** button forces the agent path when the guess is
wrong.

**Threads.** The left rail lists every chat in the project. Each keeps its own
context, so separate lines of work stay separate. New chat, double-click to
rename, ✕ to delete. Reopening a thread restores its evidence chips and its
generated files, not just the text — `MessageOut` carries `sources`, `claims`
and `artifacts` back with every message.

Switching to the P&ID tab **no longer unmounts the chat**. It is hidden, not
destroyed, so glancing at a drawing mid-answer does not lose the answer.

### Grounded, ungrounded, and the difference

| You ask | What runs | Provenance |
|---|---|---|
| "What is P-101 connected to?" | retrieval → grounded answer | cited to drawing + page |
| "Build a tracker of all instruments" | `list_entities` → `render_xlsx` | cited rows |
| "Generate an excel of the top vision models" | `draft` → `render_xlsx` | **UNVERIFIED**, model knowledge |

The third row is a deliberate boundary. The project holds no evidence for it,
so the file is labelled UNVERIFIED in the stream, in a provenance row inside
the spreadsheet itself, and as the first section of any generated document —
before the content, not after it. `calculate` remains the only route to an
engineering number and the drafting tool has no access to it.

Asked about a tag the project does not contain, the assistant now says so and
lists the tags it does have, in well under a second. It used to answer anyway:
hybrid retrieval always returns its nearest neighbours, so the packet was
never empty, and a 1B model handed P-101's evidence for a question about
XYZ-999 produced a confident description of a reactor coolant line at
confidence 0.94. Grounding is checked as "is the tag actually in the
evidence", not "is the packet non-empty".

### Answer quality depends on the chat model

The default preset is `gemma3:1b`, which is chosen to run on 16 GB CPU-only
hardware, not for accuracy. It paraphrases loosely — it will call a line an
instrument. The **Verified from Plant Memory** block appended under every
answer is deterministic, built from the graph, and is the part to trust. For
better prose run `make models` and set `OLLAMA_CHAT_MODEL=qwen3:4b`.

---

## 5. The manual demo path (what a judge sees)

```bash
make api        # terminal 1
make web        # terminal 2  →  http://localhost:3000
```

1. **Home** → create a project, or pick one.
2. **P&ID** → upload a drawing. Watch the ingestion checklist run
   render → extract → graph → index.
3. **P&ID viewer** → page strip for multi-page sheets, entity search and type
   filter, and a **⚠ N need review** button listing exactly what a validation
   rule fired on. Click an entity to highlight its bbox.
4. **Agent chat** → type a question and press **Ask** for a grounded answer
   with evidence chips; press **⚙ Build** to run the bounded agent instead.
   The activity trace shows the plan, each policy decision and each tool call.
5. **Deliverables** → the DOCX/XLSX the agent produced. **Sources** expands the
   provenance sidecar; **Download** gets the file.
6. **Trust** → egress counter, model inventory, audit log. Press **test egress**
   to fire the tripwire and watch the alarm work.

### The 90-second script

```
"Draft a Management of Change note for replacing valve XV-101."   → Build
  → plan appears, three typed tools run, DOCX lands with 16 citations
"Compute the pressure drop across the 150 mm line at 120 m3/h."   → Build
  → 0.174 bar, formula and every step shown, marked NEEDS_ENGINEERING_REVIEW
Trust → test egress  → counter increments, call fails, entry appears in the log
Trust → verify chain → ok: true; edit a row, re-run, it names the broken entry
```

---

## 6. When something fails

| Symptom | Cause | Fix |
|---|---|---|
| `Ollama reachable` skipped | Ollama not running | `ollama serve`, then `make models-small` |
| Extraction path is `none` | OCR not installed and no vision model | `pip install rapidocr-onnxruntime opencv-python` |
| Raster ingest is slow (minutes) | OCR unavailable, so the vision model ran | install OCR as above; the model path is the last resort |
| Upload appears to hang, then a refresh shows it done | **fixed** — ingestion ran on the event loop and starved the status poll | `make test` covers it; if it returns, check `pipeline.spawn` still uses a thread |
| OCR quality poor on small text | RapidOCR default | `make ocr-paddle`, then `make ocr-which` to confirm |
| Answers invent tags the drawing has no trace of | chat model too small | the **Verified from Plant Memory** block is the reliable part; `OLLAMA_CHAT_MODEL=qwen3:4b` for better prose |
| "I have no evidence for X" on a tag you can see | that tag is in a different project | the message lists the tags this project holds; switch project or upload the drawing |
| Generated file is empty apart from headers | model returned rows in an unexpected shape | fixed — rows are normalised and truncated JSON is repaired; re-run |
| Tags located in the legend, not the drawing | symbol detection found nothing | expected on very low-contrast scans; the tag is still correct, the bbox is not |
| Ingestion stuck on `processing` | previous run died mid-flight | re-trigger ingest — it recovers and re-runs idempotently |
| `graph has nodes` fails | nothing ingested yet | run without `--quick` |
| Orphaned rows reported | crashed ingest or interrupted delete | `make doctor-fix` |
| Audit chain `ok: false` | a row was edited | the report names the `seq`; investigate that entry |
| Web build fails | stale Next cache | `rm -rf apps/web/.next && npm run build` |

---

## 7. What is *not* built

Stated plainly, because the README's own position is that an honest boundary
beats an overclaim:

- **vLLM serving, sleep-mode model swapping, Grafana/Prometheus** — the model
  plane is Ollama behind a single gateway. The gateway is the seam these would
  slot into.
- **gVisor code sandbox, OPA policy engine** — the agent has no code-execution
  tool at all, so there is nothing to sandbox yet; policy is enforced in
  `agent.policy_decision`, not in OPA.
- **SSO/LDAP clearance resolution** — clearance is a per-request parameter with
  a working permission model behind it, not a resolved identity.
- **DEXPI/Proteus XML export** — the typed graph exists and is exportable; the
  DEXPI serialiser is not written.
- **Qdrant, ACL pre-filtering at the index level** — retrieval is hybrid over
  SQLite with in-Python cosine similarity.
- **Offline signed model update vault** — designed in the README, not built.
- **Manual-baseline stopwatch table** (README §5.3) — needs a human with a
  timer; the harness cannot produce it.
