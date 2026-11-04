import { describe, expect, it } from "vitest";

import { GAP_X, GAP_Y, layoutGraph, NODE_H, NODE_W } from "./layoutGraph";

const row = NODE_H + GAP_Y;
const col = NODE_W + GAP_X;

describe("layoutGraph", () => {
  it("layers by the longest path from a root (prerequisites above)", () => {
    // a → b → d, a → d, c → d: d sits below b (longest path), not right under a.
    const concepts = ["a", "b", "c", "d"].map((id) => ({ id }));
    const edges: [string, string][] = [
      ["a", "b"],
      ["b", "d"],
      ["a", "d"],
      ["c", "d"],
    ];
    const ys = Object.fromEntries(layoutGraph(concepts, edges).map((p) => [p.id, p.y]));
    expect(ys).toEqual({ a: 0, c: 0, b: row, d: 2 * row });
  });

  it("orders a layer by outline index and never overlaps", () => {
    const concepts = ["z", "y", "x"].map((id) => ({ id }));
    const placed = layoutGraph(concepts, []);
    expect(placed.map((p) => p.id)).toEqual(["z", "y", "x"]);
    expect(placed.map((p) => p.x)).toEqual([0, col, 2 * col]);
    const boxes = new Set(placed.map((p) => `${p.x},${p.y}`));
    expect(boxes.size).toBe(placed.length);
  });

  it("is stable and ignores edges to concepts outside the outline", () => {
    const concepts = [{ id: "a" }, { id: "b" }];
    const edges: [string, string][] = [
      ["outside", "a"],
      ["a", "b"],
    ];
    expect(layoutGraph(concepts, edges)).toEqual(layoutGraph(concepts, edges));
    expect(layoutGraph(concepts, edges).find((p) => p.id === "a")?.y).toBe(0);
  });

  it("centres a narrower layer under a wider one", () => {
    const concepts = ["a", "b", "c"].map((id) => ({ id }));
    const placed = layoutGraph(concepts, [
      ["a", "c"],
      ["b", "c"],
    ]);
    expect(placed.find((p) => p.id === "c")?.x).toBe(col / 2);
  });
});
