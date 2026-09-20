.PHONY: install dev api web test seed-demo ingest-demo models lint clean doctor doctor-fix verify eval demo-assets ocr-paddle ocr-which

# ─────────────────────────────────────────────────────────────
# Meshcore — local development shortcuts
# ─────────────────────────────────────────────────────────────

install:
	python -m pip install -r apps/api/requirements.txt
	cd apps/web && npm install

dev: api web

api:
	cd apps/api && python -m uvicorn app.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

test:
	cd apps/api && python -m pytest tests -v

# Seed demo project + golden dataset (offline-safe)
seed-demo:
	python scripts/seed_demo.py

# Upload + ingest a P&ID from the demo folder through the API
ingest-demo:
	python scripts/ingest_pid.py --file data/demo/pid/unit-a-pid.png --project "Demo Plant"

# Rebuild vector index from persisted chunks
rebuild-index:
	python scripts/rebuild_index.py

# ── verification and measurement ─────────────────────────────
# One command that proves the whole system works, layer by layer.
verify:
	python scripts/verify_e2e.py

# The five golden metrics (README section 5). Every number is measured.
eval:
	python scripts/eval_harness.py --json data/eval-report.json

# Regenerate the demo drawings: raster (scanned case) + vector (born-digital).
demo-assets:
	python scripts/make_demo_pid.py
	python scripts/make_vector_pid.py

# Report rows orphaned by a crashed ingest or an interrupted delete.
# SQLite does not enforce foreign keys, so these stay invisible otherwise.
doctor:
	python scripts/db_doctor.py

doctor-fix:
	python scripts/db_doctor.py --fix

# ── OCR engines ──────────────────────────────────────────────
# PaddleOCR is the better reader on dense drawing text but a ~700 MB install,
# so it is deliberately NOT in requirements.txt: `make install` must stay
# light and must not break a working machine. This is the opt-in.
ocr-paddle:
	python -m pip install "paddlepaddle>=2.6" "paddleocr>=2.7"

# Which engine will actually run, and is OpenCV present.
ocr-which:
	@cd apps/api && python -c "from app.services.pid import raster_layer, raster_geometry; print('OCR engine :', raster_layer.engine_name()); print('OpenCV     :', raster_geometry.available())"

# Pull the MVP Ollama models (large downloads — for 32 GB / GPU machines)
models:
	ollama pull qwen2.5vl:3b
	ollama pull qwen3:4b
	ollama pull nomic-embed-text

# Small-hardware preset: 16 GB RAM / Intel Core i5 (CPU-only inference).
# Total ≈ 2.8 GB download; pairs with the active .env preset.
models-small:
	ollama pull gemma3:1b
	ollama pull moondream:1.8b
	ollama pull nomic-embed-text

lint:
	cd apps/api && python -m pytest tests -q

clean:
	rm -rf data/plant_memory.db data/uploads/* data/pages/* data/indexes/* apps/web/.next