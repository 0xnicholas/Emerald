import { useEffect, useMemo, useRef } from "react"
import type {
	DocumentNodeData,
	GraphApiDocument,
	GraphApiMemory,
	GraphEdge,
	GraphNode,
	GraphThemeColors,
	MemoryNodeData,
} from "../types"

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000
const ONE_DAY_MS = 24 * 60 * 60 * 1000
const MEMORY_ORBIT_BASE = 200

export function getMemoryBorderColor(
	mem: GraphApiMemory,
	colors: GraphThemeColors,
): string {
	if (mem.isForgotten) return colors.memBorderForgotten
	if (mem.forgetAfter) {
		const msLeft = new Date(mem.forgetAfter).getTime() - Date.now()
		if (msLeft < SEVEN_DAYS_MS) return colors.memBorderExpiring
	}
	const age = Date.now() - new Date(mem.createdAt).getTime()
	if (age < ONE_DAY_MS) return colors.memBorderRecent
	return colors.memStrokeDefault
}

export function getEdgeVisualProps(edgeType: string) {
	switch (edgeType) {
		case "derives":
			return { opacity: 0.4, thickness: 1.2 }
		case "updates":
			return { opacity: 0.7, thickness: 2 }
		case "extends":
			return { opacity: 0.55, thickness: 1.5 }
		default:
			return { opacity: 0.4, thickness: 1.2 }
	}
}

/**
 * Simple deterministic hash of a string to a number in [0, 1).
 * Used for initial node placement so the force simulation has a
 * deterministic starting layout.
 */
function hashToUnit(str: string): number {
	let h = 0
	for (let i = 0; i < str.length; i++) {
		h = (Math.imul(31, h) + str.charCodeAt(i)) | 0
	}
	return ((h >>> 0) % 10000) / 10000
}

/**
 * Pure function that computes graph edges from documents.
 * Extracted from the hook for testability.
 */
export function computeEdges(documents: GraphApiDocument[]): GraphEdge[] {
	if (!documents || documents.length === 0) return []

	const result: GraphEdge[] = []
	const allNodeIds = new Set<string>()
	for (const doc of documents) {
		allNodeIds.add(doc.id)
		for (const mem of doc.memories) allNodeIds.add(mem.id)
	}

	// 1. Derives edges: document -> memory (structural)
	for (const doc of documents) {
		for (const mem of doc.memories) {
			result.push({
				id: `dm-${doc.id}-${mem.id}`,
				source: doc.id,
				target: mem.id,
				visualProps: getEdgeVisualProps("derives"),
				edgeType: "derives",
			})
		}
	}

	// 2. Memory-to-memory relation edges from backend data.
	//    Uses memoryRelations (Record<targetId, relationType>) as primary source,
	//    falls back to parentMemoryId for legacy data.
	for (const doc of documents) {
		for (const mem of doc.memories) {
			let relations: Record<string, string> = {}

			// Defensive: API may return unexpected types at runtime
			if (
				mem.memoryRelations &&
				typeof mem.memoryRelations === "object" &&
				Object.keys(mem.memoryRelations).length > 0
			) {
				relations = mem.memoryRelations
			} else if (mem.parentMemoryId) {
				// Legacy fallback: parentMemoryId implies "updates"
				relations = { [mem.parentMemoryId]: "updates" }
			}

			for (const [targetId, relationType] of Object.entries(relations)) {
				if (!allNodeIds.has(targetId)) continue
				const edgeType =
					relationType === "updates" ||
					relationType === "extends" ||
					relationType === "derives"
						? relationType
						: "updates"
				result.push({
					id: `rel-${targetId}-${mem.id}`,
					source: targetId,
					target: mem.id,
					visualProps: getEdgeVisualProps(edgeType),
					edgeType,
				})
			}
		}
	}

	return result
}

export function useGraphData(
	documents: GraphApiDocument[],
	draggingNodeId: string | null,
	canvasWidth: number,
	canvasHeight: number,
	colors: GraphThemeColors,
) {
	const nodeCache = useRef<Map<string, GraphNode>>(new Map())

	useEffect(() => {
		if (!documents || documents.length === 0) return

		const currentIds = new Set<string>()
		for (const doc of documents) {
			currentIds.add(doc.id)
			for (const mem of doc.memories) currentIds.add(mem.id)
		}

		for (const [id] of nodeCache.current.entries()) {
			if (!currentIds.has(id)) nodeCache.current.delete(id)
		}
	}, [documents])

	const nodes = useMemo(() => {
		if (!documents || documents.length === 0) return []

		const result: GraphNode[] = []
		// Spiral layout: documents form a compact spiral core, memories orbit
		// around their parent documents. The force simulation then gently
		// pushes memories outward to create the constellation/starburst effect.
		const cx = canvasWidth / 2
		const cy = canvasHeight / 2
		const docCount = documents.length
		// Wide spiral so documents start well-separated. The simulation
		// refines positions but the initial spread prevents clustering.
		const spiralScale = Math.sqrt(docCount) * 60
		// Golden angle (~137.5 deg) produces optimal packing in a spiral
		const goldenAngle = Math.PI * (3 - Math.sqrt(5))

		for (let docIdx = 0; docIdx < docCount; docIdx++) {
			const doc = documents[docIdx]
			const angle = docIdx * goldenAngle
			const radius = spiralScale * Math.sqrt((docIdx + 1) / docCount)
			const initialX = cx + Math.cos(angle) * radius
			const initialY = cy + Math.sin(angle) * radius

			let docNode = nodeCache.current.get(doc.id)
			const docData: DocumentNodeData = {
				id: doc.id,
				title: doc.title,
				summary: doc.summary,
				type: doc.documentType,
				createdAt: doc.createdAt,
				updatedAt: doc.updatedAt,
				memories: doc.memories,
			}

			if (docNode) {
				docNode.data = docData
				docNode.borderColor = colors.docStroke
				docNode.isDragging = draggingNodeId === doc.id
			} else {
				docNode = {
					id: doc.id,
					type: "document",
					x: initialX,
					y: initialY,
					data: docData,
					size: 50,
					borderColor: colors.docStroke,
					isHovered: false,
					isDragging: false,
				}
				nodeCache.current.set(doc.id, docNode)
			}
			result.push(docNode)

			const memCount = doc.memories.length
			for (let i = 0; i < memCount; i++) {
				const mem = doc.memories[i]
				if (!mem) continue
				let memNode = nodeCache.current.get(mem.id)
				const memData: MemoryNodeData = {
					...mem,
					documentId: doc.id,
					content: mem.memory,
				}

				if (memNode) {
					memNode.data = memData
					memNode.borderColor = getMemoryBorderColor(mem, colors)
					memNode.isDragging = draggingNodeId === mem.id
				} else {
					// Place memories in a ring around their parent document,
					// with slight randomness from hash for organic feel
					const memAngle =
						(i / memCount) * 2 * Math.PI + hashToUnit(mem.id) * 0.5
					const memRadius = MEMORY_ORBIT_BASE + hashToUnit(`${mem.id}-r`) * 120
					memNode = {
						id: mem.id,
						type: "memory",
						x: docNode.x + Math.cos(memAngle) * memRadius,
						y: docNode.y + Math.sin(memAngle) * memRadius,
						data: memData,
						size: 36,
						borderColor: getMemoryBorderColor(mem, colors),
						isHovered: false,
						isDragging: false,
					}
					nodeCache.current.set(mem.id, memNode)
				}
				result.push(memNode)
			}
		}

		return result
	}, [documents, canvasWidth, canvasHeight, draggingNodeId, colors])

	const edges = useMemo(() => computeEdges(documents), [documents])

	return { nodes, edges }
}
