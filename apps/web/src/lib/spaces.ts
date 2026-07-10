import type { Space } from "@/lib/types";

export const DEFAULT_SPACE_TAG = "default";

export function compareSpaces(a: Space, b: Space): number {
  if (a.containerTag === DEFAULT_SPACE_TAG) return -1;
  if (b.containerTag === DEFAULT_SPACE_TAG) return 1;
  const aAuto = a.name === `Space ${a.containerTag}`;
  const bAuto = b.name === `Space ${b.containerTag}`;
  if (aAuto && !bAuto) return 1;
  if (!aAuto && bAuto) return -1;
  return a.name.localeCompare(b.name);
}

export function getSpaceLabel(spaces: Space[], tag: string): string {
  return spaces.find((s) => s.containerTag === tag)?.name ?? tag;
}
