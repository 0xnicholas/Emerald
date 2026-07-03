// Build CJS bundle from ESM source
import { writeFileSync } from "node:fs";

const pkg = JSON.parse(
  await (await import("node:fs/promises")).readFile("package.json", "utf-8")
);

// Create a minimal CJS entry that re-exports from the ESM build
const cjs = `"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const esm = require("./index.js");
for (const key of Object.keys(esm)) {
  exports[key] = esm[key];
}
`;
writeFileSync("dist/index.cjs", cjs);
console.log("CJS bundle written to dist/index.cjs");
