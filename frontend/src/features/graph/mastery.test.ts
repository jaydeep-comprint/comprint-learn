import { describe, expect, it } from "vitest";

import type { OutlineConcept } from "@/lib/types";

import { mastery, masteryFill } from "./mastery";

function concept(overrides: Partial<OutlineConcept>): OutlineConcept {
  return {
    id: "c/x",
    title: "X",
    summary: "",
    status: "ready",
    prereqs: [],
    kps_passed: 0,
    kps_total: 3,
    waiting: null,
    brush_up: false,
    brush_up_id: null,
    ...overrides,
  };
}

describe("mastery", () => {
  it("is 0 with no knowledge, grows with parts passed, and is 1 only when learned", () => {
    expect(mastery(concept({ status: "locked" }))).toBe(0);
    expect(mastery(concept({ status: "ready" }))).toBe(0);
    const one = mastery(concept({ status: "in_progress", kps_passed: 1 }));
    const two = mastery(concept({ status: "in_progress", kps_passed: 2 }));
    const all = mastery(concept({ status: "in_progress", kps_passed: 3 }));
    expect(0).toBeLessThan(one);
    expect(one).toBeLessThan(two);
    expect(two).toBeLessThan(all);
    expect(all).toBeLessThan(1); // the darkest blue is reserved for learned
    expect(mastery(concept({ status: "learned" }))).toBe(1);
    expect(mastery(concept({ status: null }))).toBe(0); // staff preview
  });

  it("mixes white with the full blue", () => {
    expect(masteryFill(0)).toContain(" 0%");
    expect(masteryFill(1)).toContain(" 100%");
  });
});
