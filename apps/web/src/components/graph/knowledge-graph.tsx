"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3-force";
import type { SearchMemory } from "@/lib/types";
import { memoryTypeLabel, truncate } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────

interface GraphNode extends SimulationNodeDatum {
  id: string;
  label: string;
  type: string;
  score: number;
  radius: number;
  content: string;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  label?: string;
}

interface KnowledgeGraphProps {
  memories: SearchMemory[];
  onNodeClick?: (memory: SearchMemory) => void;
  zoomLevel?: number;
  onZoomChange?: (z: number) => void;
}

// ─── Constants ────────────────────────────────────────────────────────

const TYPE_CONFIG: Record<string, { color: string; emoji: string; glow: string }> = {
  fact:     { color: "#34d399", emoji: "📌", glow: "rgba(52,211,153,0.3)" },
  preference: { color: "#a78bfa", emoji: "❤️", glow: "rgba(167,139,250,0.3)" },
  episodic: { color: "#fbbf24", emoji: "💭", glow: "rgba(251,191,36,0.3)" },
};

const NS = "http://www.w3.org/2000/svg";

// ─── Component ────────────────────────────────────────────────────────

export function KnowledgeGraph({
  memories,
  onNodeClick,
  zoomLevel = 1,
  onZoomChange,
}: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  // Responsive
  useEffect(() => {
    const update = () => {
      if (!containerRef.current) return;
      setDimensions({
        width: containerRef.current.clientWidth,
        height: Math.max(500, containerRef.current.clientHeight),
      });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Build graph data
  const graphData = useCallback(() => {
    const nodes: GraphNode[] = memories.map((m) => ({
      id: m.id,
      label: m.content.slice(0, 40),
      content: m.content,
      type: m.memory_type,
      score: m.score ?? 0.5,
      radius: Math.max(20, Math.min(38, 14 + Math.sqrt(m.content.length) * 0.5)),
    }));

    const links: GraphLink[] = [];
    const byDoc = new Map<string, string[]>();
    for (const m of memories) {
      if (m.document_id) {
        const arr = byDoc.get(m.document_id) ?? [];
        arr.push(m.id);
        byDoc.set(m.document_id, arr);
      }
    }
    for (const ids of byDoc.values()) {
      for (let i = 0; i < ids.length - 1; i++)
        links.push({ source: ids[i], target: ids[i + 1], label: "document" });
    }

    const byType = new Map<string, string[]>();
    for (const m of memories) {
      const arr = byType.get(m.memory_type) ?? [];
      arr.push(m.id);
      byType.set(m.memory_type, arr);
    }
    for (const ids of byType.values()) {
      if (ids.length > 1 && ids.length <= 6) {
        for (let i = 0; i < ids.length - 1; i++) {
          const exists = links.some(
            (l) =>
              (l.source === ids[i] && l.target === ids[i + 1]) ||
              (l.source === ids[i + 1] && l.target === ids[i])
          );
          if (!exists) links.push({ source: ids[i], target: ids[i + 1], label: "type" });
        }
      }
    }
    return { nodes, links };
  }, [memories]);

  const { nodes, links } = useMemo(() => graphData(), [graphData]);

  // Render
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || nodes.length === 0) return;

    const { width, height } = dimensions;
    const svgEl = svg;

    // Clear
    let child = svgEl.lastChild;
    while (child) { svgEl.removeChild(child); child = svgEl.lastChild; }

    // Root group for zoom
    const root = document.createElementNS(NS, "g");
    svgEl.appendChild(root);

    // Defs
    const defs = document.createElementNS(NS, "defs");
    // Arrows
    const marker = document.createElementNS(NS, "marker");
    marker.setAttribute("id", "arrow");
    marker.setAttribute("viewBox", "0 -5 10 10");
    marker.setAttribute("refX", "25");
    marker.setAttribute("refY", "0");
    marker.setAttribute("markerWidth", "6");
    marker.setAttribute("markerHeight", "6");
    marker.setAttribute("orient", "auto");
    const arrowPath = document.createElementNS(NS, "path");
    arrowPath.setAttribute("d", "M0,-5L10,0L0,5");
    arrowPath.setAttribute("fill", "#4ba0fa");
    marker.appendChild(arrowPath);
    defs.appendChild(marker);

    // Glow filters
    for (const [type, cfg] of Object.entries(TYPE_CONFIG)) {
      const filter = document.createElementNS(NS, "filter");
      filter.setAttribute("id", `glow-${type}`);
      filter.setAttribute("x", "-50%");
      filter.setAttribute("y", "-50%");
      filter.setAttribute("width", "200%");
      filter.setAttribute("height", "200%");
      const blur = document.createElementNS(NS, "feGaussianBlur");
      blur.setAttribute("stdDeviation", "6");
      blur.setAttribute("result", "blur");
      filter.appendChild(blur);
      const merge = document.createElementNS(NS, "feMerge");
      const mn1 = document.createElementNS(NS, "feMergeNode");
      mn1.setAttribute("in", "blur");
      merge.appendChild(mn1);
      const mn2 = document.createElementNS(NS, "feMergeNode");
      mn2.setAttribute("in", "SourceGraphic");
      merge.appendChild(mn2);
      filter.appendChild(merge);
      defs.appendChild(filter);
    }
    root.appendChild(defs);

    // Physics
    const simulation = forceSimulation<GraphNode>(nodes)
      .force("link", forceLink<GraphNode, GraphLink>(links).id((d) => d.id).distance(130))
      .force("charge", forceManyBody().strength(-300))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collision", forceCollide<GraphNode>().radius((d) => d.radius + 15));
    simRef.current = simulation;

    // Links
    const linkGroup = document.createElementNS(NS, "g");
    const linkEls: SVGLineElement[] = [];
    for (const _ of links) {
      const line = document.createElementNS(NS, "line");
      line.setAttribute("stroke", "#263348");
      line.setAttribute("stroke-width", "1.5");
      line.setAttribute("stroke-dasharray", "4 3");
      line.setAttribute("marker-end", "url(#arrow)");
      linkGroup.appendChild(line);
      linkEls.push(line);
    }
    root.appendChild(linkGroup);

    // Link labels
    const llGroup = document.createElementNS(NS, "g");
    const llEls: SVGTextElement[] = [];
    for (const l of links) {
      if (l.label) {
        const t = document.createElementNS(NS, "text");
        t.setAttribute("font-size", "8");
        t.setAttribute("fill", "#a0aec4");
        t.setAttribute("text-anchor", "middle");
        t.textContent = l.label;
        llGroup.appendChild(t);
        llEls.push(t);
      }
    }
    root.appendChild(llGroup);

    // Nodes
    const nodeGroup = document.createElementNS(NS, "g");
    const nodeMap = new Map<string, SVGGElement>();

    for (const n of nodes) {
      const g = document.createElementNS(NS, "g");
      g.setAttribute("cursor", "pointer");
      const cfg = TYPE_CONFIG[n.type] ?? { color: "#52525b", emoji: "📄", glow: "rgba(82,82,91,0.3)" };

      // Glow circle (behind)
      const glow = document.createElementNS(NS, "circle");
      glow.setAttribute("r", String(n.radius + 4));
      glow.setAttribute("fill", "none");
      glow.setAttribute("stroke", cfg.color);
      glow.setAttribute("stroke-width", "1.5");
      glow.setAttribute("opacity", "0.4");
      glow.setAttribute("filter", `url(#glow-${n.type})`);
      g.appendChild(glow);

      // Main circle
      const circle = document.createElementNS(NS, "circle");
      circle.setAttribute("r", String(n.radius));
      circle.setAttribute("fill", "#101822");
      circle.setAttribute("stroke", cfg.color);
      circle.setAttribute("stroke-width", "2");
      g.appendChild(circle);

      // Emoji
      const emoji = document.createElementNS(NS, "text");
      emoji.setAttribute("text-anchor", "middle");
      emoji.setAttribute("dy", "0.35em");
      emoji.setAttribute("font-size", String(Math.max(11, n.radius * 0.65)));
      emoji.textContent = cfg.emoji;
      g.appendChild(emoji);

      // Label below
      const label = document.createElementNS(NS, "text");
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("dy", String(n.radius + 16));
      label.setAttribute("font-size", "9");
      label.setAttribute("fill", "#a0aec4");
      label.textContent = n.label + (n.label.length >= 40 ? "…" : "");
      g.appendChild(label);

      // Hover
      g.addEventListener("mouseenter", () => setHoveredId(n.id));
      g.addEventListener("mouseleave", () => setHoveredId(null));

      // Click
      g.addEventListener("click", (e) => {
        e.stopPropagation();
        const mem = memories.find((m) => m.id === n.id);
        if (mem && onNodeClick) onNodeClick(mem);
      });

      // Drag
      let dragActive = false;
      const dragStart = (e: MouseEvent) => {
        e.stopPropagation();
        dragActive = true;
        simulation.alphaTarget(0.3).restart();
        n.fx = n.x; n.fy = n.y;
        window.addEventListener("mousemove", dragMove);
        window.addEventListener("mouseup", dragEnd);
      };
      const dragMove = (e: MouseEvent) => {
        if (!dragActive) return;
        const rect = svgEl.getBoundingClientRect();
        n.fx = (e.clientX - rect.left) / zoomLevel;
        n.fy = (e.clientY - rect.top) / zoomLevel;
      };
      const dragEnd = () => {
        dragActive = false;
        simulation.alphaTarget(0);
        n.fx = null; n.fy = null;
        window.removeEventListener("mousemove", dragMove);
        window.removeEventListener("mouseup", dragEnd);
      };
      g.addEventListener("mousedown", dragStart);

      nodeGroup.appendChild(g);
      nodeMap.set(n.id, g);
    }
    root.appendChild(nodeGroup);

    // Zoom
    root.setAttribute("transform",
      `translate(${width / 2},${height / 2}) scale(${zoomLevel}) translate(${-width / 2},${-height / 2})`
    );

    // Tick
    simulation.on("tick", () => {
      for (let i = 0; i < linkEls.length; i++) {
        const d = links[i];
        const s = d.source as GraphNode;
        const t = d.target as GraphNode;
        linkEls[i].setAttribute("x1", String(s.x ?? 0));
        linkEls[i].setAttribute("y1", String(s.y ?? 0));
        linkEls[i].setAttribute("x2", String(t.x ?? 0));
        linkEls[i].setAttribute("y2", String(t.y ?? 0));
      }
      let li = 0;
      for (const l of links) {
        if (!l.label) continue;
        const s = l.source as GraphNode;
        const t = l.target as GraphNode;
        if (llEls[li]) {
          llEls[li].setAttribute("x", String(((s.x ?? 0) + (t.x ?? 0)) / 2));
          llEls[li].setAttribute("y", String(((s.y ?? 0) + (t.y ?? 0)) / 2));
        }
        li++;
      }
      for (const n of nodes) {
        const g = nodeMap.get(n.id);
        if (g) g.setAttribute("transform", `translate(${n.x ?? 0},${n.y ?? 0})`);
      }
    });

    return () => { simulation.stop(); };
  }, [nodes, links, dimensions, zoomLevel, onNodeClick, memories]);

  const hoveredMemory = hoveredId ? memories.find((m) => m.id === hoveredId) : null;

  if (memories.length === 0) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center text-fg-subtle">
        <p className="text-sm">Search memories to see the graph</p>
      </div>
    );
  }

  const typeCounts = { fact: 0, preference: 0, episodic: 0 };
  for (const m of memories) {
    if (m.memory_type in typeCounts) typeCounts[m.memory_type as keyof typeof typeCounts]++;
  }

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="overflow-visible"
        style={{ minHeight: "500px" }}
      />

      {/* Legend */}
      <div className="pointer-events-none absolute bottom-4 left-4 flex items-center gap-4 rounded-[18px] border border-surface-border bg-surface-card/60 px-4 py-2 backdrop-blur-md shadow-[0_12px_40px_rgba(0,0,0,0.22)]">
        {Object.entries(TYPE_CONFIG).map(([type, cfg]) => (
          <span key={type} className="flex items-center gap-1.5 text-[11px] text-fg-muted">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: cfg.color }} />
            {cfg.emoji} {memoryTypeLabel(type)}
            <span className="text-fg-faint">({typeCounts[type as keyof typeof typeCounts]})</span>
          </span>
        ))}
        <span className="text-fg-faint text-[10px]">| Drag to rearrange</span>
      </div>

      {/* Hover popover */}
      {hoveredMemory && (
        <div className="pointer-events-none absolute top-4 right-4 max-w-xs rounded-[18px] border border-surface-border bg-surface-card/80 p-3 backdrop-blur-xl shadow-[0_12px_40px_rgba(0,0,0,0.34)]">
          <p className="text-xs font-medium text-fg-primary">{truncate(hoveredMemory.content, 120)}</p>
          {hoveredMemory.summary && (
            <p className="mt-1 text-[10px] text-fg-muted">{hoveredMemory.summary}</p>
          )}
        </div>
      )}
    </div>
  );
}
