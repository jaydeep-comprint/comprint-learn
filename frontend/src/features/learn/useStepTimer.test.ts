import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useStepTimer } from "@/features/learn/useStepTimer";

let now = 0;
let visibility: DocumentVisibilityState = "visible";

function setVisibility(v: DocumentVisibilityState) {
  visibility = v;
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("useStepTimer", () => {
  beforeEach(() => {
    now = 0;
    visibility = "visible";
    vi.spyOn(performance, "now").mockImplementation(() => now);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibility,
    });
  });

  it("reports active seconds when the step changes, pausing while the tab is hidden", () => {
    const report = vi.fn();
    const { rerender } = renderHook(({ step }) => useStepTimer(step, report), {
      initialProps: { step: "intro" as string | null },
    });
    now = 5_000;
    setVisibility("hidden");
    expect(report).toHaveBeenLastCalledWith("intro", 5, { keepalive: true });

    now = 65_000; // a minute away: not counted
    setVisibility("visible");
    now = 68_000;
    rerender({ step: "check" });
    expect(report).toHaveBeenLastCalledWith("intro", 3, { keepalive: false });
    expect(report).toHaveBeenCalledTimes(2);
  });

  it("caps a report at 600 s and skips 0 s", () => {
    const report = vi.fn();
    const { rerender, unmount } = renderHook(({ step }) => useStepTimer(step, report), {
      initialProps: { step: "intro" as string | null },
    });
    now = 3_000_000;
    rerender({ step: "check" });
    expect(report).toHaveBeenLastCalledWith("intro", 600, { keepalive: false });
    unmount(); // 0 s on "check"
    expect(report).toHaveBeenCalledTimes(1);
  });

  it("flushes on pagehide with keepalive", () => {
    const report = vi.fn();
    renderHook(() => useStepTimer("kp:kp1", report));
    now = 12_400;
    window.dispatchEvent(new Event("pagehide"));
    expect(report).toHaveBeenCalledWith("kp:kp1", 12, { keepalive: true });
  });

  it("does nothing for a null step (staff preview)", () => {
    const report = vi.fn();
    const { unmount } = renderHook(() => useStepTimer(null, report));
    now = 50_000;
    setVisibility("hidden");
    unmount();
    expect(report).not.toHaveBeenCalled();
  });
});
