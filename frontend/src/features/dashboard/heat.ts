import type { Band, HeatCell, HeatState } from "@/lib/types";

/** Heatmap and Memory-mode colours (spec 010). Every state also has a glyph and a label, so
 * colour is never the only cue. */
export const STATE_LABELS: Record<HeatState, string> = {
  locked: "Locked",
  ready: "Ready",
  in_progress: "In progress",
  stuck: "Stuck",
  learned: "Learned",
};

export const BAND_LABELS: Record<Band, string> = {
  strong: "memory strong",
  fading: "memory fading",
  weak: "memory weak",
  none: "no memory data",
};

/** Fill colours for learned concepts by memory band (darkest = strongest). */
export const BAND_FILL: Record<Band, string> = {
  strong: "#047857",
  fading: "#34d399",
  weak: "#bbf7d0",
  none: "#d1fae5",
};

export const BAND_GLYPH: Record<Band, string> = {
  strong: "●",
  fading: "◐",
  weak: "○",
  none: "–",
};

export const STATE_GLYPH: Record<Exclude<HeatState, "learned">, string> = {
  locked: "",
  ready: "",
  in_progress: "…",
  stuck: "!",
};

/** Tailwind classes per cell (learned cells use `BAND_FILL` inline). */
export const STATE_CLASS: Record<Exclude<HeatState, "learned">, string> = {
  locked: "bg-muted",
  ready: "bg-background border border-slate-400",
  in_progress: "bg-amber-300 text-amber-950",
  stuck: "bg-red-500 text-white",
};

export function cellLabel(cell: HeatCell): string {
  if (cell.state === "learned") return `Learned, ${BAND_LABELS[cell.band ?? "none"]}`;
  return STATE_LABELS[cell.state];
}

export const MEMORY_GREY = "#f1f5f9";
