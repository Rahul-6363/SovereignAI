"use client";
/** Screen 4 — Plant Memory: interactive graph + embedded P&ID preview.
 *
 * Force-directed layout computed with requestAnimationFrame on plain SVG.
 * Clicking a node (a) shows its drawing bbox in the preview pane and
 * (b) opens the inspector for full details.
 */
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { EntityDetail, EntityRec, MemoryGraph } from "@/lib/types";
import { Badge, Button, ConfidenceBar, EmptyState, Spinner } from "./ui";
import PidViewer from "./PidViewer";

interface Positioned {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  node: MemoryGraph["nodes"][number];
}

export default function MemoryPane({
  projectId,
  onInspector,
}: {
  projectId: number;
  onInspector: (d: EntityDetail) => void;
}) {
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [preview, setPreview] = useState<{
    imageUrl: string;
    bbox: number[] | null;
    label: string;
    entities: EntityRec[];
  } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [positions, setPositions] = useState<Positioned[]>([]);
  const dragRef = useRef<{ id: string; dx: number; dy: number } | null>(null);

  // load graph
  useEffect(() => {
    (async () => {
      try {
        setGraph(await api.projectGraph(projectId));
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [projectId]);

  // seed positions + run force simulation
  useEffect(() => {
    if (!graph || graph.nodes.length === 0) return;
    const W = 800;
    const H = 600;
    let nodes: Positioned[] = graph.nodes.map((n, i) => {
      const a = (2 * Math.PI * i) / graph.nodes.length;
      const r = 180 + 40 * Math.sin(i * 3.7);
      return {
        id: n.id,
        x: W / 2 + r * Math.cos(a),
        y: H / 2 + r * Math.sin(a),
        vx: 0,
        vy: 0,
        node: n,
      };
    });

    const edges = graph.edges.map((e) => ({
      s: nodes.find((n) => n.id === e.source),
      t: nodes.find((n) => n.id === e.target),
      rel: e.relation,
    }));

    let alpha = 0.9;
    let raf = 0;
    const tick = () => {
      if (dragRef.current) alpha = Math.max(alpha, 0.15);
      // repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = b.x - a.x || 0.01;
          const dy = b.y - a.y || 0.01;
          const d2 = dx * dx + dy * dy;
          const f = (2200 * alpha) / Math.max(d2, 100);
          const d = Math.sqrt(d2);
          const fx = (dx / d) * f;
          const fy = (dy / d) * f;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }
      // springs
      for (const e of edges) {
        if (!e.s || !e.t) continue;
        const dx = e.t.x - e.s.x || 0.01;
        const dy = e.t.y - e.s.y || 0.01;
        const d = Math.sqrt(dx * dx + dy * dy);
        const f = ((d - 110) * 0.06 * alpha) / Math.max(d, 1);
        const fx = dx * f;
        const fy = dy * f;
        e.s.vx += fx;
        e.s.vy += fy;
        e.t.vx -= fx;
        e.t.vy -= fy;
      }
      // centering + damping + integrate
      for (const n of nodes) {
        n.vx += ((W / 2 - n.x) * 0.0025 * alpha) / 1;
        n.vy += ((H / 2 - n.y) * 0.0035 * alpha) / 1;
        n.vx *= 0.82;
        n.vy *= 0.82;
        if (dragRef.current?.id !== n.id) {
          n.x = Math.max(40, Math.min(W - 40, n.x + n.vx));
          n.y = Math.max(40, Math.min(H - 40, n.y + n.vy));
        }
      }
      alpha *= 0.995;
      setPositions([...nodes]);
      raf = requestAnimationFrame(tick);
      if (alpha < 0.01) cancelAnimationFrame(raf);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [graph]);
  const selectNode = async (pos: Positioned) => {
    setSelected(pos.id);
    setDetailLoading(true);
    setDetail(null);
    try {
      const d = await api.memoryEntity(projectId, pos.node.tag || pos.node.id);
      setDetail(d);
      setPreview({
        imageUrl: d.image_url,
        bbox: d.entity.bbox,
        label: d.entity.canonical_tag,
        entities: [],
      });
      onInspector(d);
    } catch {
      setDetail(null);
      setPreview(null);
    } finally {
      setDetailLoading(false);
    }
  };
  if (error) {
    return (
      <div className="p-6 text-sm text-rose-300">{error}</div>
    );
  }
  if (!graph) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-zinc-500">
        <Spinner /> Loading memory graph…
      </div>
    );
  }
  if (graph.nodes.length === 0) {
    return (
      <EmptyState
        title="No memory yet"
        hint="Ingest a P&ID to build the plant memory graph."
      />
    );
  }

  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

  const handleDragStart = (e: React.MouseEvent, pos: Positioned) => {
    const pt = svgRef.current?.getBoundingClientRect();
    if (!pt) return;
    const W = 800;
    const H = 600;
    dragRef.current = {
      id: pos.id,
      dx: ((e.clientX - pt.left) / pt.width) * W - pos.x,
      dy: ((e.clientY - pt.top) / pt.height) * H - pos.y,
    };
    const move = (ev: MouseEvent) => {
      const box = svgRef.current?.getBoundingClientRect();
      if (!box || !dragRef.current) return;
      const x = ((ev.clientX - box.left) / box.width) * W - dragRef.current.dx;
      const y = ((ev.clientY - box.top) / box.height) * H - dragRef.current.dy;
      setPositions((ps) =>
        ps.map((p) =>
          p.id === dragRef.current!.id
            ? { ...p, x: Math.max(40, Math.min(W - 40, x)), y: Math.max(40, Math.min(H - 40, y)) }
            : p,
        ),
      );
    };
    const up = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const selectedNode = selected ? nodeById.get(selected) : null;

  return (
    <div className="flex h-full min-h-0">
      {/* graph */}
      <div className="relative min-h-0 flex-1">
        <svg
          ref={svgRef}
          viewBox="0 0 800 600"
          className="h-full w-full"
          onMouseDown={(e) => e.preventDefault()}
        >
          {positions.map((p) =>
            graph.edges
              .filter((e) => e.source === p.id)
              .map((e) => {
                const t = positions.find((q) => q.id === e.target);
                if (!t) return null;
                const dim = selected && selected !== p.id && selected !== t.id;
                return (
                  <line
                    key={`${e.source}-${e.target}-${e.relation}`}
                    x1={p.x}
                    y1={p.y}
                    x2={t.x}
                    y2={t.y}
                    stroke={dim ? "#2c2c2c" : "#4a4a4a"}
                    strokeWidth={1}
                  />
                );
              }),
          )}
          {positions.map((p) => {
            const dim = selected && selected !== p.id;
            const r = 10 + Math.min(10, (p.node.confidence ?? 0.5) * 10);
            return (
              <g
                key={p.id}
                transform={`translate(${p.x},${p.y})`}
                className="cursor-pointer"
                opacity={dim ? 0.35 : 1}
                onMouseDown={(e) => {
                  e.stopPropagation();
                  handleDragStart(e, p);
                }}
                onClick={() => selectNode(p)}
              >
                <circle
                  r={selected === p.id ? r + 3 : r}
                  fill={selected === p.id ? "#d97757" : "#3f3f3f"}
                  stroke={selected === p.id ? "#e8967a" : "#666"}
                  strokeWidth={1.5}
                />
                <text
                  y={r + 12}
                  textAnchor="middle"
                  className="fill-zinc-300 font-mono"
                  fontSize={11}
                >
                  {p.node.tag || p.node.id}
                </text>
              </g>
            );
          })}
        </svg>
        <div className="absolute left-3 top-3 flex items-center gap-2">
          <Badge color="zinc">{graph.nodes.length} entities</Badge>
          <Badge color="zinc">{graph.edges.length} links</Badge>
          <span className="text-[10px] text-zinc-600">
            drag nodes · click to inspect
          </span>
        </div>
        {detailLoading && (
          <div className="absolute right-3 top-3 flex items-center gap-2 text-xs text-zinc-500">
            <Spinner className="h-3 w-3" /> loading…
          </div>
        )}
      </div>

      {/* preview pane */}
      <div className="flex w-[380px] shrink-0 flex-col border-l border-ink-800">
        {preview ? (
          <PidViewer
            imageUrl={preview.imageUrl}
            bbox={preview.bbox}
            label={preview.label}
            className="flex-1"
          />
        ) : (
          <EmptyState
            title="Select a node"
            hint="Click an entity to preview where it sits on the drawing."
          />
        )}
        {selectedNode && (
          <div className="border-t border-ink-800 p-3 text-xs">
            <div className="mb-1 flex items-center gap-2">
              <span className="font-mono text-sm text-zinc-100">
                {selectedNode.tag}
              </span>
              <Badge color="zinc">{selectedNode.type}</Badge>
            </div>
            <p className="mb-2 text-zinc-500">{selectedNode.label}</p>
            <ConfidenceBar value={selectedNode.confidence} />
            <div className="mt-2 flex gap-2">
              <Button
                variant="outline"
                onClick={() => selected && selectNode({
                  id: selected,
                  x: 0, y: 0, vx: 0, vy: 0, node: selectedNode,
                })}
              >
                Open in inspector
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
