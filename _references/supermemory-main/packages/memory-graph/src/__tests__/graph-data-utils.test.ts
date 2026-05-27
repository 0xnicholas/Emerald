import { describe, it, expect } from "vitest"
import {
	getMemoryBorderColor,
	getEdgeVisualProps,
} from "../hooks/use-graph-data"
import { DEFAULT_COLORS } from "../constants"
import type { GraphApiMemory } from "../types"

function makeMemory(overrides: Partial<GraphApiMemory> = {}): GraphApiMemory {
	return {
		id: "m1",
		memory: "test",
		isStatic: false,
		spaceId: "default",
		isLatest: true,
		isForgotten: false,
		forgetAfter: null,
		forgetReason: null,
		version: 1,
		parentMemoryId: null,
		rootMemoryId: null,
		createdAt: "2024-01-01",
		updatedAt: "2024-01-01",
		...overrides,
	}
}

describe("getMemoryBorderColor", () => {
	const colors = DEFAULT_COLORS

	it("returns forgotten color for forgotten memories", () => {
		const mem = makeMemory({ isForgotten: true })
		expect(getMemoryBorderColor(mem, colors)).toBe(colors.memBorderForgotten)
	})

	it("returns expiring color for memories expiring within 7 days", () => {
		const soon = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString()
		const mem = makeMemory({ forgetAfter: soon })
		expect(getMemoryBorderColor(mem, colors)).toBe(colors.memBorderExpiring)
	})

	it("returns recent color for memories created within 24 hours", () => {
		const recent = new Date(Date.now() - 1000).toISOString()
		const mem = makeMemory({ createdAt: recent })
		expect(getMemoryBorderColor(mem, colors)).toBe(colors.memBorderRecent)
	})

	it("returns default color for normal memories", () => {
		const old = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()
		const mem = makeMemory({ createdAt: old })
		expect(getMemoryBorderColor(mem, colors)).toBe(colors.memStrokeDefault)
	})

	it("forgotten takes priority over expiring", () => {
		const soon = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString()
		const mem = makeMemory({ isForgotten: true, forgetAfter: soon })
		expect(getMemoryBorderColor(mem, colors)).toBe(colors.memBorderForgotten)
	})
})

describe("getEdgeVisualProps", () => {
	it("returns correct props for derives edges", () => {
		const props = getEdgeVisualProps("derives")
		expect(props.opacity).toBeCloseTo(0.4)
		expect(props.thickness).toBeCloseTo(1.2)
	})

	it("returns correct props for updates edges", () => {
		const props = getEdgeVisualProps("updates")
		expect(props.opacity).toBeCloseTo(0.7)
		expect(props.thickness).toBeCloseTo(2)
	})

	it("returns correct props for extends edges", () => {
		const props = getEdgeVisualProps("extends")
		expect(props.opacity).toBeCloseTo(0.55)
		expect(props.thickness).toBeCloseTo(1.5)
	})

	it("returns default props for unknown edge types", () => {
		const props = getEdgeVisualProps("unknown")
		expect(props.opacity).toBeCloseTo(0.4)
		expect(props.thickness).toBeCloseTo(1.2)
	})
})
