"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
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
import type { GraphNode, GraphEdge } from "@/lib/types";
import { memoryTypeLabel } from "@/lib/utils";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────

interface SimNode extends SimulationNodeDatum {
  id: string;
  label: string;
  type: string;
  confidence: number;
  radius: number;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  relType: string;
}

interface KnowledgeGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick?: (nodeId: string) => void;
  zoomLevel?: number;
  selectedTypes?: string[];
  searchQuery?: string;
}

// ─── Constants ────────────────────────────────────────────────────────

const TYPE_CONFIG: Record<string, { color: string; emoji: string; glow: string }> = {
  fact:     { color: "#34d399", emoji: "📌", glow: "rgba(52,211,153,0.3)" },
  preference: { color: "#a78bfa", emoji: "❤️", glow: "rgba(167,139,250,0.3)" },
  episodic: { color: "#fbbf24", emoji: "💭", glow: "rgba(251,191,36,0.3)" },
};

const EDGE_COLORS: Record<string, string> = {
  UPDATES: "#f97316",
  EXTENDS: "#4ba0fa",
  DERIVES_FROM: "#a78bfa",
};

const EDGE_LABELS: Record<string, string> = {
  UPDATES: "updates",
  EXTENDS: "extends",
  DERIVES_FROM: "derives",
};

const NS = "http://www.w3.org/2000/svg";

// ─── Component ────────────────────────────────────────────────────────

export function KnowledgeGraph({
  nodes: inputNodes,
  edges: inputEdges,
  onNodeClick,
  zoomLevel = 1,
  selectedTypes,
  searchQuery,
}: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

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

  // Filter nodes by type
  const filteredNodes = useMemo(
    () => (selectedTypes?.length ? inputNodes.filter((n) => selectedTypes.includes(n.type)) : inputNodes),
    [inputNodes, selectedTypes]
  );
  const filteredIds = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes]);
  const filteredEdges = useMemo(
    () => inputEdges.filter((e) => filteredIds.has(e.source) && filteredIds.has(e.target)),
    [inputEdges, filteredIds]
  );

  // Search highlight
  const searchLower = searchQuery?.toLowerCase() ?? "";

  // Build sim data
  const { simNodes, simLinks } = useMemo(() => {
    const nodes: SimNode[] = filteredNodes.map((n) => ({
      id: n.id,
      label: n.label,
      type: n.type,
      confidence: n.confidence,
      radius: Math.max(20, Math.min(38, 14 + n.label.length * 0.3)),
    }));
    const links: SimLink[] = filteredEdges.map((e) => ({
      source: e.source,
      target: e.target,
      relType: e.type,
    }));
    return { simNodes: nodes, simLinks: links };
  }, [filteredNodes, filteredEdges]);

  // Render
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || simNodes.length === 0) return;

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

    // Arrow markers per relationship type
    for (const [type, color] of Object.entries(EDGE_COLORS)) {
      const marker = document.createElementNS(NS, "marker");
      marker.setAttribute("id", `arrow-${type}`);
      marker.setAttribute("viewBox", "0 -5 10 10");
      marker.setAttribute("refX", "28");
      marker.setAttribute("refY", "0");
      marker.setAttribute("markerWidth", "7");
      marker.setAttribute("markerHeight", "7");
      marker.setAttribute("orient", "auto");
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", "M0,-5L10,0L0,5");
      path.setAttribute("fill", color);
      marker.appendChild(path);
      defs.appendChild(marker);
    }

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
    const simulation = forceSimulation<SimNode>(simNodes)
      .force("link", forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance(150))
      .force("charge", forceManyBody().strength(-350))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collision", forceCollide<SimNode>().radius((d) => d.radius + 20));
    simRef.current = simulation;

    // Links
    const linkGroup = document.createElementNS(NS, "g");
    const linkEls: SVGLineElement[] = [];
    const linkLabels: SVGTextElement[] = [];

    for (const link of simLinks) {
      const color = EDGE_COLORS[link.relType] ?? "#263348";
      const isHovered = hoveredEdge === `${link.source}-${link.target}`;

      // Line
      const line = document.createElementNS(NS, "line");
      line.setAttribute("stroke", color);
      line.setAttribute("stroke-width", isHovered ? "2.5" : "1.5");
      line.setAttribute("stroke-opacity", isHovered ? "1" : "0.6");
      line.setAttribute("stroke-dasharray", link.relType === "UPDATES" ? "6 3" : "4 3");
      line.setAttribute("marker-end", `url(#arrow-${link.relType})`);
      line.setAttribute("data-source", String(link.source));
      line.setAttribute("data-target", String(link.target));

      // Hover for edge
      line.addEventListener("mouseenter", () => {
        setHoveredEdge(`${link.source}-${link.target}`);
      });
      line.addEventListener("mouseleave", () => {
        setHoveredEdge(null);
      });

      linkGroup.appendChild(line);
      linkEls.push(line);

      // Label
      const lbl = document.createElementNS(NS, "text");
      lbl.setAttribute("font-size", "8");
      lbl.setAttribute("fill", color);
      lbl.setAttribute("text-anchor", "middle");
      lbl.setAttribute("dy", "-5");
      lbl.setAttribute("font-weight", "600");
      lbl.setAttribute("opacity", isHovered ? "1" : "0.7");
      lbl.textContent = EDGE_LABELS[link.relType] ?? link.relType;
      linkLabels.push(lbl);
      linkGroup.appendChild(lbl);
    }
    root.appendChild(linkGroup);

    // Nodes
    const nodeGroup = document.createElementNS(NS, "g");
    const nodeMap = new Map<string, SVGGElement>();

    for (const n of simNodes) {
      const g = document.createElementNS(NS, "g");
      g.setAttribute("cursor", "pointer");
      g.setAttribute("data-id", n.id);
      const cfg = TYPE_CONFIG[n.type] ?? { color: "#52525b", emoji: "📄", glow: "rgba(82,82,91,0.3)" };

      // Search match
      const matchesSearch = searchLower && n.label.toLowerCase().includes(searchLower);

      // Glow circle
      const glow = document.createElementNS(NS, "circle");
      glow.setAttribute("r", String(n.radius + 5));
      glow.setAttribute("fill", "none");
      glow.setAttribute("stroke", cfg.color);
      glow.setAttribute("stroke-width", matchesSearch ? "3" : "1.5");
      glow.setAttribute("opacity", matchesSearch ? "1" : "0.35");
      glow.setAttribute("filter", `url(#glow-${n.type})`);
      g.appendChild(glow);

      // Main circle
      const circle = document.createElementNS(NS, "circle");
      circle.setAttribute("r", String(n.radius));
      circle.setAttribute("fill", "#101822");
      circle.setAttribute("stroke", cfg.color);
      circle.setAttribute("stroke-width", matchesSearch ? "3" : "2");
      g.appendChild(circle);

      // Emoji
      const emoji = document.createElementNS(NS, "text");
      emoji.setAttribute("text-anchor", "middle");
      emoji.setAttribute("dy", "0.35em");
      emoji.setAttribute("font-size", String(Math.max(11, n.radius * 0.65)));
      emoji.textContent = cfg.emoji;
      g.appendChild(emoji);

      // Label
      const label = document.createElementNS(NS, "text");
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("dy", String(n.radius + 16));
      label.setAttribute("font-size", "9");
      label.setAttribute("fill", "#a0aec4");
      label.setAttribute("font-weight", matchesSearch ? "700" : "400");
      const displayLabel = n.label.length > 40 ? n.label.slice(0, 38) + "…" : n.label;
      label.textContent = displayLabel;
      g.appendChild(label);

      // Hover
      g.addEventListener("mouseenter", (e) => {
        setHoveredId(n.id);
        const rect = svgEl.getBoundingClientRect();
        setTooltipPos({ x: (e as MouseEvent).clientX - rect.left, y: (e as MouseEvent).clientY - rect.top - 10 });
      });
      g.addEventListener("mouseleave", () => setHoveredId(null));

      // Click
      g.addEventListener("click", () => {
        onNodeClick?.(n.id);
      });

      nodeGroup.appendChild(g);
      nodeMap.set(n.id, g);
    }
    root.appendChild(nodeGroup);

    // Zoom
    const scale = zoomLevel;
    root.setAttribute("transform",
      `translate(${width / 2},${height / 2}) scale(${scale}) translate(${-width / 2},${-height / 2})`
    );

    // Tick
    simulation.on("tick", () => {
      for (let i = 0; i < linkEls.length; i++) {
        const d = simLinks[i];
        const s = d.source as SimNode;
        const t = d.target as SimNode;
        linkEls[i].setAttribute("x1", String(s.x ?? 0));
        linkEls[i].setAttribute("y1", String(s.y ?? 0));
        linkEls[i].setAttribute("x2", String(t.x ?? 0));
        linkEls[i].setAttribute("y2", String(t.y ?? 0));

        // Position label at midpoint
        if (linkLabels[i]) {
          linkLabels[i].setAttribute("x", String(((s.x ?? 0) + (t.x ?? 0)) / 2));
          linkLabels[i].setAttribute("y", String(((s.y ?? 0) + (t.y ?? 0)) / 2));
        }
      }
      for (const n of simNodes) {
        const g = nodeMap.get(n.id);
        if (g) g.setAttribute("transform", `translate(${n.x ?? 0},${n.y ?? 0})`);
      }
    });

    return () => { simulation.stop(); };
  }, [simNodes, simLinks, dimensions, zoomLevel, onNodeClick, hoveredEdge, searchLower]);

  const hoveredNode = inputNodes.find((n) => n.id === hoveredId);

  if (inputNodes.length === 0) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center text-fg-subtle">
        <p className="text-sm">No memories to display in the graph</p>
      </div>
    );
  }

  const typeCounts = { fact: 0, preference: 0, episodic: 0 };
  for (const n of inputNodes) {
    if (n.type in typeCounts) typeCounts[n.type as keyof typeof typeCounts]++;
  }
  const edgeTypeCounts: Record<string, number> = {};
  for (const e of inputEdges) {
    edgeTypeCounts[e.type] = (edgeTypeCounts[e.type] ?? 0) + 1;
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
      <div className="pointer-events-none absolute bottom-4 left-4 flex flex-wrap items-center gap-3 rounded-[18px] border border-surface-border bg-surface-card/60 px-4 py-2.5 backdrop-blur-md shadow-lg">
        <span className="text-[10px] font-semibold text-fg-faint uppercase tracking-wider mr-1">Nodes</span>
        {Object.entries(TYPE_CONFIG).map(([type, cfg]) => (
          <span key={type} className="flex items-center gap-1.5 text-[11px] text-fg-muted">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: cfg.color }} />
            {cfg.emoji} {memoryTypeLabel(type)}
            <span className="text-fg-faint">({typeCounts[type as keyof typeof typeCounts]})</span>
          </span>
        ))}
        {Object.keys(edgeTypeCounts).length > 0 && (
          <>
            <span className="w-px h-4 bg-surface-border/50" />
            <span className="text-[10px] font-semibold text-fg-faint uppercase tracking-wider mr-1">Edges</span>
            {Object.entries(edgeTypeCounts).map(([type, count]) => (
              <span key={type} className="flex items-center gap-1 text-[11px] text-fg-muted">
                <span className="w-3 h-0.5 rounded-full" style={{ background: EDGE_COLORS[type] ?? "#52525b" }} />
                {type.toLowerCase()}
                <span className="text-fg-faint">({count})</span>
              </span>
            ))}
          </>
        )}
        <span className="text-fg-faint text-[10px] ml-1">| Drag to rearrange</span>
      </div>

      {/* Search result count */}
      {searchQuery && (
        <div className="absolute top-4 left-4 rounded-xl border border-surface-border bg-surface-card/80 px-3 py-1.5 text-xs text-fg-muted backdrop-blur-md">
          Searching: <span className="text-fg-primary font-medium">"{searchQuery}"</span>
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredNode && (
        <div
          className="pointer-events-none absolute max-w-xs rounded-[18px] border border-surface-border bg-surface-card/90 p-3 backdrop-blur-xl shadow-lg"
          style={{ left: tooltipPos.x + 15, top: tooltipPos.y - 30, transform: "translateY(-100%)" }}
        >
          <p className="text-xs font-medium text-fg-primary leading-relaxed">{hoveredNode.label}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[10px] text-fg-muted">{memoryTypeLabel(hoveredNode.type)}</span>
            <span className="text-[10px] text-fg-faint">{Math.round(hoveredNode.confidence * 100)}%</span>
          </div>
        </div>
      )}
    </div>
  );
}
