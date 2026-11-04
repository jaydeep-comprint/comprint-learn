import { describe, expect, it } from "vitest";

import { normaliseUnit, unitPlaceholder, unitPreview } from "@/features/learn/unitPreview";

describe("unitPreview", () => {
  it("reads the server's aliases and forms", () => {
    expect(unitPreview("km/hr")).toBe("km·h⁻¹");
    expect(unitPreview("kmph")).toBe("km·h⁻¹");
    expect(unitPreview("km h^-1")).toBe("km·h⁻¹");
    expect(unitPreview("mps")).toBe("m·s⁻¹");
    expect(unitPreview("m s^-1")).toBe("m·s⁻¹");
    expect(unitPreview("m/s²")).toBe("m·s⁻²");
    expect(unitPreview("secs")).toBe("s");
    expect(unitPreview("Ω")).toBe("ohm");
    expect(unitPreview("N·m")).toBe("N·m");
  });

  it("is case-sensitive and says nothing for what it can't read", () => {
    expect(unitPreview("ms")).toBe("ms"); // milliseconds
    expect(unitPreview("n")).toBeNull();
    expect(unitPreview("metres")).toBeNull();
    expect(unitPreview("")).toBeNull();
    expect(unitPreview("m/")).toBeNull();
  });

  it("normalises like the server", () => {
    expect(normaliseUnit(" km  h^-1 ")).toBe("km*h^-1");
    expect(normaliseUnit("x/kmph")).toBe("x/(km/h)");
    expect(unitPlaceholder("m/s")).toBe("unit, e.g. m/s");
  });
});
