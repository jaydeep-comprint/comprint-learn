import { describe, expect, it } from "vitest";

import { edgeId, highlight } from "./highlight";

// root → mid → leaf, other → leaf, unrelated stands alone.
const prereqs = new Map<string, string[]>([
  ["root", []],
  ["mid", ["root"]],
  ["other", []],
  ["leaf", ["mid", "other"]],
  ["unrelated", []],
]);
const edges: [string, string][] = [
  ["root", "mid"],
  ["mid", "leaf"],
  ["other", "leaf"],
];

describe("highlight", () => {
  it("marks direct prerequisites, distant ancestors and dims the rest", () => {
    const h = highlight("leaf", prereqs, edges);
    expect(Object.fromEntries(h.nodes)).toEqual({
      leaf: "selected",
      mid: "direct",
      other: "direct",
      root: "distant",
      unrelated: "dim",
    });
    expect(h.edges.get(edgeId("mid", "leaf"))).toBe("direct");
    expect(h.edges.get(edgeId("other", "leaf"))).toBe("direct");
    expect(h.edges.get(edgeId("root", "mid"))).toBe("distant");
  });

  it("dims descendants and their edges", () => {
    const h = highlight("mid", prereqs, edges);
    expect(h.nodes.get("leaf")).toBe("dim");
    expect(h.edges.get(edgeId("mid", "leaf"))).toBe("dim");
    expect(h.edges.get(edgeId("root", "mid"))).toBe("direct");
  });
});
