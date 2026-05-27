import * as d3 from "d3-force"
import type { GraphEdge, GraphNode } from "../types"
import { FORCE_CONFIG } from "../constants"

export class ForceSimulation {
	private sim: d3.Simulation<GraphNode, GraphEdge> | null = null

	init(nodes: GraphNode[], edges: GraphEdge[]): void {
		this.destroy()

		try {
			// Only use structural edges (derives, updates) for the force layout.
			// "extends" edges are visual-only -- they connect documents sharing a
			// spaceId but should not pull documents together into a single mass.
			const structuralEdges = edges.filter((e) => e.edgeType !== "extends")

			this.sim = d3
				.forceSimulation<GraphNode>(nodes)
				.alphaDecay(FORCE_CONFIG.alphaDecay)
				.alphaMin(FORCE_CONFIG.alphaMin)
				.velocityDecay(FORCE_CONFIG.velocityDecay)

			this.sim.force(
				"link",
				d3
					.forceLink<GraphNode, GraphEdge>(structuralEdges)
					.id((d) => d.id)
					.distance((link) =>
						link.edgeType === "derives"
							? FORCE_CONFIG.docMemoryDistance
							: FORCE_CONFIG.linkDistance,
					)
					.strength((link) => {
						if (link.edgeType === "derives")
							return FORCE_CONFIG.linkStrength.docMemory
						if (link.edgeType === "updates")
							return FORCE_CONFIG.linkStrength.version
						return FORCE_CONFIG.linkStrength.fallback
					}),
			)

			this.sim.force(
				"charge",
				d3.forceManyBody<GraphNode>().strength(FORCE_CONFIG.chargeStrength),
			)

			this.sim.force(
				"collide",
				d3
					.forceCollide<GraphNode>()
					.radius((d) =>
						d.type === "document"
							? FORCE_CONFIG.collisionRadius.document
							: FORCE_CONFIG.collisionRadius.memory,
					)
					.strength(FORCE_CONFIG.collisionStrength),
			)

			this.sim.force("x", d3.forceX().strength(FORCE_CONFIG.centeringStrength))
			this.sim.force("y", d3.forceY().strength(FORCE_CONFIG.centeringStrength))

			this.sim.stop()
			this.sim.alpha(1)
			for (let i = 0; i < FORCE_CONFIG.preSettleTicks; i++) this.sim.tick()
			this.sim.alphaTarget(0).restart()
		} catch (e) {
			console.error("ForceSimulation.init failed:", e)
			this.destroy()
		}
	}

	update(nodes: GraphNode[], edges: GraphEdge[]): void {
		if (!this.sim) return
		this.sim.nodes(nodes)
		const linkForce = this.sim.force<d3.ForceLink<GraphNode, GraphEdge>>("link")
		if (linkForce)
			linkForce.links(edges.filter((e) => e.edgeType !== "extends"))
	}

	reheat(): void {
		this.sim?.alphaTarget(FORCE_CONFIG.alphaTarget).restart()
	}

	coolDown(): void {
		this.sim?.alphaTarget(0)
	}

	isActive(): boolean {
		return (this.sim?.alpha() ?? 0) > FORCE_CONFIG.alphaMin
	}

	destroy(): void {
		if (this.sim) {
			this.sim.stop()
			this.sim = null
		}
	}
}
