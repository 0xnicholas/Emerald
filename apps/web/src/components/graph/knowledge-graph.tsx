"use client";

import { useEffect, useRef, useState, useCallback } from "react";
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
import { memoryTypeLabel } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────

interface GraphNode extends SimulationNodeDatum {
  id: string;
  label: string;
  type: string;
  score: number;
  radius: number;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  label?: string;
}

interface KnowledgeGraphProps {
  memories: SearchMemory[];
  onNodeClick?: (memory: SearchMemory) => void;
  zoomLevel?: number;
}

// ─── Constants ────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  fact: "#059669",
  preference: "#7c3aed",
  episodic: "#d97706",
};

const TYPE_EMOJIS: Record<string, string> = {
  fact: "📌",
  preference: "❤️",
  episodic: "💭",
};

const NS = "http://www.w3.org/2000/svg";

// ─── Component ────────────────────────────────────────────────────────

export function KnowledgeGraph({
  memories,
  onNodeClick,
  zoomLevel = 1,
}: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Responsive
  useEffect(() => {
    const updateSize = () => {
      if (!containerRef.current) return;
      setDimensions({
        width: containerRef.current.clientWidth,
        height: Math.max(500, containerRef.current.clientHeight),
      });
    };
    updateSize();
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  // Graph data builder
  const graphData = useCallback(() => {
    const nodes: GraphNode[] = memories.map((m) => ({
      id: m.id,
      label: m.content.slice(0, 40),
      type: m.memory_type,
      score: m.score ?? 0.5,
      radius: Math.max(16, Math.min(36, 12 + Math.sqrt(m.content.length) * 0.5)),
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
      for (let i = 0; i < ids.length - 1; i++) {
        links.push({ source: ids[i], target: ids[i + 1], label: "同文档" });
      }
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
          if (!exists) {
            links.push({ source: ids[i], target: ids[i + 1], label: "同类" });
          }
        }
      }
    }

    return { nodes, links };
  }, [memories]);

  // Render
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || memories.length === 0) return;

    const { width, height } = dimensions;
    const { nodes, links } = graphData();

    // ── Setup SVG ──
    const svgEl = svg as unknown as SVGSVGElement;
    let child = svgEl.lastChild;
    while (child) {
      svgEl.removeChild(child);
      child = svgEl.lastChild;
    }

    // Root group for zoom
    const root = document.createElementNS(NS, "g");
    root.setAttribute("class", "root");
    svgEl.appendChild(root);

    // Defs
    const defs = document.createElementNS(NS, "defs");
    const marker = document.createElementNS(NS, "marker");
    marker.setAttribute("id", "arrow");
    marker.setAttribute("viewBox", "0 -5 10 10");
    marker.setAttribute("refX", "20");
    marker.setAttribute("refY", "0");
    marker.setAttribute("markerWidth", "6");
    marker.setAttribute("markerHeight", "6");
    marker.setAttribute("orient", "auto");
    const arrowPath = document.createElementNS(NS, "path");
    arrowPath.setAttribute("d", "M0,-5L10,0L0,5");
    arrowPath.setAttribute("fill", "#a1a1aa");
    marker.appendChild(arrowPath);
    defs.appendChild(marker);
    root.appendChild(defs);

    // ── Physics ──
    const simulation = forceSimulation<GraphNode>(nodes)
      .force(
        "link",
        forceLink<GraphNode, GraphLink>(links)
          .id((d) => d.id)
          .distance(120)
      )
      .force("charge", forceManyBody().strength(-250))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collision", forceCollide<GraphNode>().radius((d) => d.radius + 12));

    simRef.current = simulation;

    // ── Link lines ──
    const linkGroup = document.createElementNS(NS, "g");
    linkGroup.setAttribute("class", "links");
    const linkElements: SVGLineElement[] = [];
    for (const _ of links) {
      const line = document.createElementNS(NS, "line");
      line.setAttribute("stroke", "#d4d4d8");
      line.setAttribute("stroke-width", "1.5");
      line.setAttribute("stroke-dasharray", "4 2");
      line.setAttribute("marker-end", "url(#arrow)");
      linkGroup.appendChild(line);
      linkElements.push(line);
    }
    root.appendChild(linkGroup);

    // ── Link labels ──
    const labelGroup = document.createElementNS(NS, "g");
    labelGroup.setAttribute("class", "link-labels");
    const labelElements: SVGTextElement[] = [];
    for (const l of links) {
      if (l.label) {
        const text = document.createElementNS(NS, "text");
        text.setAttribute("font-size", "9");
        text.setAttribute("fill", "#71717a");
        text.setAttribute("text-anchor", "middle");
        text.textContent = l.label;
        labelGroup.appendChild(text);
        labelElements.push(text);
      }
    }
    root.appendChild(labelGroup);

    // ── Nodes ──
    const nodeGroup = document.createElementNS(NS, "g");
    nodeGroup.setAttribute("class", "nodes");
    const nodeRects: Record<string, SVGGElement> = {};

    for (const n of nodes) {
      const g = document.createElementNS(NS, "g");
      g.setAttribute("cursor", "pointer");

      const circle = document.createElementNS(NS, "circle");
      circle.setAttribute("r", String(n.radius));
      circle.setAttribute("fill", TYPE_COLORS[n.type] ?? "#6b7280");
      circle.setAttribute("stroke", "#fff");
      circle.setAttribute("stroke-width", "2");
      circle.setAttribute("opacity", "0.85");
      g.appendChild(circle);

      const emoji = document.createElementNS(NS, "text");
      emoji.setAttribute("text-anchor", "middle");
      emoji.setAttribute("dy", "0.35em");
      emoji.setAttribute("font-size", String(Math.max(10, n.radius * 0.6)));
      emoji.textContent = TYPE_EMOJIS[n.type] ?? "📄";
      g.appendChild(emoji);

      const label = document.createElementNS(NS, "text");
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("dy", String(n.radius + 14));
      label.setAttribute("font-size", "10");
      label.setAttribute("fill", "#52525b");
      label.textContent = n.label + (n.label.length >= 40 ? "…" : "");
      g.appendChild(label);

      const title = document.createElementNS(NS, "title");
      title.textContent = `${memoryTypeLabel(n.type)} | 置信度: ${Math.round(n.score * 100)}%\n${n.label}`;
      g.appendChild(title);

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
        n.fx = n.x;
        n.fy = n.y;
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
        n.fx = null;
        n.fy = null;
        window.removeEventListener("mousemove", dragMove);
        window.removeEventListener("mouseup", dragEnd);
      };
      g.addEventListener("mousedown", dragStart);

      nodeGroup.appendChild(g);
      nodeRects[n.id] = g;
    }
    root.appendChild(nodeGroup);

    // ── Apply zoom ──
    root.setAttribute(
      "transform",
      `translate(${width / 2},${height / 2}) scale(${zoomLevel}) translate(${-width / 2},${-height / 2})`
    );

    // ── Tick ──
    simulation.on("tick", () => {
      for (let i = 0; i < linkElements.length; i++) {
        const d = links[i];
        const sx = (d.source as GraphNode)?.x ?? 0;
        const sy = (d.source as GraphNode)?.y ?? 0;
        const tx = (d.target as GraphNode)?.x ?? 0;
        const ty = (d.target as GraphNode)?.y ?? 0;
        linkElements[i].setAttribute("x1", String(sx));
        linkElements[i].setAttribute("y1", String(sy));
        linkElements[i].setAttribute("x2", String(tx));
        linkElements[i].setAttribute("y2", String(ty));
      }
      for (let i = 0; i < labelElements.length; i++) {
        const d = links.filter((l) => l.label)[i];
        if (!d) continue;
        const sx = (d.source as GraphNode)?.x ?? 0;
        const sy = (d.source as GraphNode)?.y ?? 0;
        const tx = (d.target as GraphNode)?.x ?? 0;
        const ty = (d.target as GraphNode)?.y ?? 0;
        labelElements[i].setAttribute("x", String((sx + tx) / 2));
        labelElements[i].setAttribute("y", String((sy + ty) / 2));
      }
      for (const n of nodes) {
        const g = nodeRects[n.id];
        if (g) {
          g.setAttribute("transform", `translate(${n.x ?? 0},${n.y ?? 0})`);
        }
      }
    });

    return () => {
      simulation.stop();
    };
  }, [memories, dimensions, graphData, onNodeClick, zoomLevel]);

  if (memories.length === 0) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px] text-zinc-400">
        <p>搜索记忆后将在图谱中展示</p>
      </div>
    );
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
      <div className="pointer-events-none absolute bottom-3 left-3 flex gap-3 text-xs text-zinc-400">
        <span>📌 事实</span>
        <span>❤️ 偏好</span>
        <span>💭 情节</span>
        <span className="ml-2 text-zinc-300">| 拖拽节点调整布局</span>
      </div>
    </div>
  );
}
