import type { OutlineConcept } from "@/lib/types";

// In-progress shades stay light enough for dark text (>= 4.5:1); learned jumps to the full blue,
// which takes white text. Nothing lands in between, where neither text colour reads well.
const IN_PROGRESS_MAX = 0.5;

/** How much of a concept the student knows, 0..1, for the map's colour grade: white (nothing)
 * to dark blue (learned). In-progress concepts stop short of the learned shade. */
export function mastery(concept: OutlineConcept): number {
  if (concept.status === "learned") return 1;
  if (concept.status !== "in_progress" || concept.parts_total === 0) return 0;
  return Math.min(concept.parts_passed / concept.parts_total, 1) * IN_PROGRESS_MAX;
}

/** From this mastery on, the fill is dark enough that text switches to white. */
export const DARK_FROM = 0.7;

/** The node's fill: the empty shade (white) mixed with the full-mastery blue. */
export function masteryFill(m: number): string {
  return `color-mix(in oklch, var(--mastery-full) ${Math.round(m * 100)}%, var(--mastery-empty))`;
}
