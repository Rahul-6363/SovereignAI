# Meshcore — Web UI

Next.js 15 (App Router) + TypeScript + Tailwind CSS frontend for **Meshcore**,
the sovereign on-premise agentic AI workbench. P&ID is a first-class capability
of the main workspace: selecting it opens the *existing* P&ID upload /
processing / review interface rather than a second implementation.

| View | Where |
|---|---|
| Main Meshcore workspace | `/` — Claude-like composer, capability launcher, recent projects & conversations, egress counter, product-status boundary |
| Project workspace | `/projects/[id]` — `?view=overview\|chat\|pid\|memory\|deliverables` |
| Overview / launcher | `?view=overview` — capabilities, project stats, return path |
| Agent chat | `?view=chat` — SSE streaming, tool/activity trace, attachments, deliverables |
| P&ID capability | `?view=pid` — the completed module's upload + explorer + inspector |
| Plant Memory | `?view=memory` — entity graph visualization |
| Deliverables | `?view=deliverables` — generated DOCX/XLSX artefacts |
| Trust / Runtime | trust drawer + live egress tripwire (available everywhere) |
| Projects management | `/workspace` — create / list / delete projects |

Deep links are how the main workspace reaches a capability:

```text
/projects/<id>?view=pid&from=meshcore      → existing P&ID interface
/projects/<id>?view=chat&q=<task>          → handoff from the home composer
/projects/<id>?view=chat&conversation=<id> → restore a conversation
```

## Run

```bash
npm install
npm run dev        # http://localhost:3000
```

The dev server proxies all `/api/*` calls to the FastAPI backend
(`http://localhost:8000` by default; override with `API_BASE_URL`,
e.g. inside docker-compose it is `http://api:8000`).

Production build:

```bash
npm run build
npm run start
```

## Conventions

- All backend access flows through `lib/api.ts` (same-origin `/api/...`).
- Chat streaming is POST-based SSE parsed in `lib/sse.ts` (EventSource cannot POST).
- No component library dependency; accessible primitives live in `components/ui.tsx`.
- Capability names and their maturity badges have a single source of truth in
  `components/CapabilityGrid.tsx` (`CAPABILITIES`), matching the roadmap phases.
