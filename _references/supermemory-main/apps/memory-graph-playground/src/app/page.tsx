"use client"

import { useState, useCallback, useMemo } from "react"
import {
	MemoryGraph,
	type DocumentWithMemories,
	type GraphApiDocument,
	type GraphApiMemory,
} from "@supermemory/memory-graph"
import { generateMockGraphData } from "@supermemory/memory-graph/mock-data"

interface DocumentsResponse {
	documents: DocumentWithMemories[]
	pagination: {
		currentPage: number
		limit: number
		totalItems: number
		totalPages: number
	}
}

/** Convert the external API format to the internal graph format */
function toGraphDocuments(docs: DocumentWithMemories[]): GraphApiDocument[] {
	return docs.map((doc) => ({
		id: doc.id,
		title: doc.title,
		summary: doc.summary ?? null,
		documentType: doc.documentType,
		createdAt: doc.createdAt,
		updatedAt: doc.updatedAt,
		memories: doc.memories.map(
			(mem): GraphApiMemory => ({
				id: mem.id,
				memory: mem.content,
				isStatic: mem.isStatic ?? false,
				spaceId: mem.spaceId ?? "",
				isLatest: mem.isLatest ?? true,
				isForgotten: mem.isForgotten ?? false,
				forgetAfter: mem.forgetAfter ?? null,
				forgetReason: mem.forgetReason ?? null,
				version: mem.version ?? 1,
				parentMemoryId: mem.parentMemoryId ?? null,
				rootMemoryId: mem.rootMemoryId ?? null,
				createdAt: mem.createdAt,
				updatedAt: mem.updatedAt,
			}),
		),
	}))
}

export default function Home() {
	const [apiKey, setApiKey] = useState("")
	const [documents, setDocuments] = useState<DocumentWithMemories[]>([])
	const [isLoading, setIsLoading] = useState(false)
	const [error, setError] = useState<Error | null>(null)
	const [showGraph, setShowGraph] = useState(false)
	const [stressTestCount, setStressTestCount] = useState(0)

	// State for slideshow
	const [isSlideshowActive, setIsSlideshowActive] = useState(false)

	// Mock data for stress testing
	const [mockData, setMockData] = useState<{
		documents: GraphApiDocument[]
	} | null>(null)

	const PAGE_SIZE = 500

	const fetchDocuments = useCallback(
		async (page: number, append = false) => {
			if (!apiKey) return

			if (page === 1) {
				setIsLoading(true)
			}
			setError(null)

			try {
				const response = await fetch("/api/graph", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
					},
					body: JSON.stringify({
						apiKey,
						page,
						limit: PAGE_SIZE,
						sort: "createdAt",
						order: "desc",
					}),
				})

				if (!response.ok) {
					const errorData = await response.json()
					throw new Error(errorData.error || "Failed to fetch documents")
				}

				const data: DocumentsResponse = await response.json()

				if (append) {
					setDocuments((prev) => [...prev, ...data.documents])
				} else {
					setDocuments(data.documents)
				}

				setShowGraph(true)
				setMockData(null)
				setStressTestCount(0)
			} catch (err) {
				setError(err instanceof Error ? err : new Error("Unknown error"))
			} finally {
				setIsLoading(false)
			}
		},
		[apiKey],
	)

	const handleSubmit = (e: React.FormEvent) => {
		e.preventDefault()
		if (apiKey) {
			setDocuments([])
			fetchDocuments(1)
		}
	}

	const handleStressTest = (count: number) => {
		const data = generateMockGraphData({
			documentCount: count,
			memoriesPerDoc: [2, 5],
			seed: 12345,
		})
		setMockData({ documents: data.documents })
		setDocuments([])
		setStressTestCount(count)
		setShowGraph(true)
		setError(null)
	}

	// Toggle slideshow
	const handleToggleSlideshow = () => {
		setIsSlideshowActive((prev) => !prev)
	}

	// Handle slideshow node change
	const handleSlideshowNodeChange = useCallback((nodeId: string | null) => {
		console.log("Slideshow showing node:", nodeId)
	}, [])

	// Handle slideshow stop
	const handleSlideshowStop = useCallback(() => {
		setIsSlideshowActive(false)
	}, [])

	// Convert real documents to graph format
	const graphDocuments = useMemo(() => {
		if (mockData) return mockData.documents
		return toGraphDocuments(documents)
	}, [documents, mockData])

	const displayCount = mockData ? stressTestCount : documents.length

	return (
		<div className="flex flex-col h-screen bg-zinc-950">
			{/* Header */}
			<header className="shrink-0 border-b border-zinc-800 bg-zinc-900 px-6 py-4">
				<div className="flex items-center justify-between">
					<div>
						<h1 className="text-xl font-semibold text-white">
							Memory Graph Playground
						</h1>
						<p className="text-sm text-zinc-400">
							Test the @supermemory/memory-graph package
						</p>
					</div>

					<form onSubmit={handleSubmit} className="flex items-center gap-3">
						<input
							type="password"
							placeholder="Enter your Supermemory API key"
							value={apiKey}
							onChange={(e) => setApiKey(e.target.value)}
							className="w-80 rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-sm text-white placeholder-zinc-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
						/>
						<button
							type="submit"
							disabled={!apiKey || isLoading}
							className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{isLoading ? "Loading..." : "Load Graph"}
						</button>
					</form>
				</div>
			</header>

			{/* Controls Panel */}
			<div className="shrink-0 border-b border-zinc-800 bg-zinc-900/50 px-6 py-3">
				<div className="flex items-center justify-between text-sm">
					<div className="flex items-center gap-6">
						<div className="flex items-center gap-2">
							<span className="text-zinc-400">Documents:</span>
							<span className="font-mono text-emerald-400">{displayCount}</span>
						</div>
						{stressTestCount > 0 && (
							<span className="rounded bg-amber-900/50 px-2 py-0.5 text-xs text-amber-400">
								Stress Test Mode
							</span>
						)}
					</div>
					<div className="flex items-center gap-3">
						{/* Stress test buttons */}
						<span className="text-zinc-500 text-xs">Stress Test:</span>
						{[50, 100, 200, 500].map((count) => (
							<button
								key={count}
								type="button"
								onClick={() => handleStressTest(count)}
								className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
									stressTestCount === count
										? "bg-amber-600 text-white"
										: "border border-zinc-700 text-zinc-300 hover:bg-zinc-800"
								}`}
							>
								{count} docs
							</button>
						))}
						<div className="h-6 w-px bg-zinc-700" />
						<button
							type="button"
							onClick={handleToggleSlideshow}
							className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors flex items-center gap-1.5 ${
								isSlideshowActive
									? "bg-blue-600 text-white hover:bg-blue-700"
									: "border border-zinc-700 text-zinc-300 hover:bg-zinc-800"
							}`}
						>
							<svg
								width="12"
								height="12"
								viewBox="0 0 24 24"
								fill="currentColor"
								aria-hidden="true"
							>
								{isSlideshowActive ? (
									<rect x="6" y="6" width="12" height="12" />
								) : (
									<path d="M8 5v14l11-7z" />
								)}
							</svg>
							Slideshow
						</button>
					</div>
				</div>
			</div>

			{/* Main content */}
			<main className="flex-1 overflow-hidden">
				{!showGraph ? (
					<div className="flex h-full items-center justify-center">
						<div className="max-w-md text-center">
							<div className="mb-6 text-6xl">
								<svg
									className="mx-auto h-16 w-16 text-zinc-600"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									aria-hidden="true"
								>
									<path
										strokeLinecap="round"
										strokeLinejoin="round"
										strokeWidth={1.5}
										d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
									/>
								</svg>
							</div>
							<h2 className="mb-2 text-xl font-semibold text-white">
								Get Started
							</h2>
							<p className="mb-6 text-zinc-400">
								Enter your API key above, or click a stress test button to
								generate mock data.
							</p>
							<div className="text-left text-sm text-zinc-500">
								<p className="mb-2 font-medium text-zinc-400">
									Features to test:
								</p>
								<ul className="list-inside list-disc space-y-1">
									<li>Pan and zoom the graph</li>
									<li>Click on nodes to see details</li>
									<li>Drag nodes around</li>
									<li>Arrow key navigation</li>
									<li>Stress test with 50-500 documents</li>
									<li>FPS counter (shown during stress tests)</li>
								</ul>
							</div>
						</div>
					</div>
				) : (
					<div className="h-full w-full">
						<MemoryGraph
							documents={graphDocuments}
							isLoading={isLoading}
							error={error}
							variant="consumer"
							maxNodes={1000}
							showFps={stressTestCount > 0}
							isSlideshowActive={isSlideshowActive}
							onSlideshowNodeChange={handleSlideshowNodeChange}
							onSlideshowStop={handleSlideshowStop}
						>
							<div className="flex h-full items-center justify-center">
								<p className="text-zinc-400">
									No memories found. Add some content to see your graph.
								</p>
							</div>
						</MemoryGraph>
					</div>
				)}
			</main>
		</div>
	)
}
