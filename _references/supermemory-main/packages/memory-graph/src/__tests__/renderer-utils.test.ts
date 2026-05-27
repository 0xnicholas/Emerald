import { describe, expect, test } from "vitest"
import { lightenColor } from "../canvas/renderer"

describe("lightenColor", () => {
	test("lightens a dark hex color", () => {
		// #1B1F24 lightened by 0.08 → each channel +20 (0.08*255≈20)
		const result = lightenColor("#1B1F24", 0.08)
		// R: 0x1B(27)+20=47=0x2f, G: 0x1F(31)+20=51=0x33, B: 0x24(36)+20=56=0x38
		expect(result).toBe("#2f3338")
	})

	test("clamps channels at 255", () => {
		// #FFFFFF lightened by 0.1 → all channels clamped at 255
		const result = lightenColor("#ffffff", 0.1)
		expect(result).toBe("#ffffff")
	})

	test("handles zero amount (no change)", () => {
		const result = lightenColor("#1B1F24", 0)
		expect(result).toBe("#1b1f24")
	})

	test("returns input unchanged for 3-digit hex", () => {
		expect(lightenColor("#abc", 0.1)).toBe("#abc")
	})

	test("returns input unchanged for rgb() format", () => {
		expect(lightenColor("rgb(27, 31, 36)", 0.1)).toBe("rgb(27, 31, 36)")
	})

	test("returns input unchanged for 8-digit hex with alpha", () => {
		expect(lightenColor("#1B1F24FF", 0.1)).toBe("#1B1F24FF")
	})

	test("caches result for repeated calls", () => {
		const first = lightenColor("#0D2034", 0.08)
		const second = lightenColor("#0D2034", 0.08)
		expect(first).toBe(second)
	})

	test("cache invalidates on different input", () => {
		const a = lightenColor("#0D2034", 0.08)
		const b = lightenColor("#1B1F24", 0.08)
		expect(a).not.toBe(b)
	})

	test("cache invalidates on different amount", () => {
		const a = lightenColor("#1B1F24", 0.05)
		const b = lightenColor("#1B1F24", 0.1)
		expect(a).not.toBe(b)
	})

	test("handles hex without # prefix", () => {
		const result = lightenColor("1B1F24", 0.08)
		expect(result).toBe("#2f3338")
	})
})
