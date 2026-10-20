// @vitest-environment node
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { collectAssets, isAllowedAsset } from "./content-assets";

describe("isAllowedAsset", () => {
  it.each([
    "physics-9-10/01-motion/distance-and-displacement/img/path.svg",
    "maths-9-10/02-pair/graphical/img/lines.PNG",
    "python-basics/01-basics/loops/img/sub/flow.webp",
    "a/01-b/c/img/x.jpg",
  ])("allows %s", (rel) => expect(isAllowedAsset(rel)).toBe(true));

  it.each([
    "physics-9-10/01-motion/acceleration/concept.yaml",
    "physics-9-10/01-motion/acceleration/kp-1-worked.md",
    "physics-9-10/01-motion/acceleration/img/notes.md",
    "physics-9-10/01-motion/acceleration/img/../concept.yaml",
    "physics-9-10/01-motion/acceleration/img/../../x.svg",
    "physics-9-10/course.yaml",
    "physics-9-10/01-motion/acceleration/diagram.svg",
    "physics-9-10/01-motion/acceleration/img/.hidden.svg",
    "../secrets/img/x.svg",
    "/etc/img/x.svg",
    "physics-9-10/01-motion/acceleration/img/x.gif",
  ])("rejects %s", (rel) => expect(isAllowedAsset(rel)).toBe(false));
});

describe("collectAssets", () => {
  it("finds only images inside concept img folders", () => {
    const root = mkdtempSync(path.join(tmpdir(), "content-"));
    const concept = path.join(root, "physics", "01-motion", "speed");
    mkdirSync(path.join(concept, "img"), { recursive: true });
    writeFileSync(path.join(concept, "img", "a.svg"), "<svg/>");
    writeFileSync(path.join(concept, "img", "b.yaml"), "secret: 1");
    writeFileSync(path.join(concept, "concept.yaml"), "id: speed");
    writeFileSync(path.join(concept, "intro.md"), "# Speed");
    expect(collectAssets(root)).toEqual(["physics/01-motion/speed/img/a.svg"]);
  });

  it("includes the sample SVG diagram", () => {
    const assets = collectAssets(path.resolve(__dirname, "../../content"));
    expect(assets.some((a) => a.startsWith("physics-9-10/") && a.endsWith(".svg"))).toBe(true);
    expect(assets.every((a) => !a.endsWith(".yaml") && !a.endsWith(".md"))).toBe(true);
  });
});
