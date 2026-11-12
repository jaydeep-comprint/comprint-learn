import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkerIn, WorkerOut } from "@/features/code/protocol";
import { usePython, type WorkerLike } from "@/features/code/usePython";

class FakeWorker implements WorkerLike {
  static all: FakeWorker[] = [];
  onmessage: ((event: MessageEvent<WorkerOut>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  sent: WorkerIn[] = [];
  terminated = false;

  constructor() {
    FakeWorker.all.push(this);
  }

  postMessage(message: WorkerIn) {
    this.sent.push(message);
  }

  terminate() {
    this.terminated = true;
  }

  emit(message: WorkerOut) {
    this.onmessage?.({ data: message } as MessageEvent<WorkerOut>);
  }
}

const TESTS = [
  { visible: true, returns: "value" as const, args: "[1]", stdin: null },
  { visible: false, returns: "value" as const, args: "[2]", stdin: null },
];

describe("usePython", () => {
  beforeEach(() => {
    FakeWorker.all = [];
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  function setup() {
    const hook = renderHook(() => usePython(() => new FakeWorker()));
    const first = FakeWorker.all[0]!;
    expect(first.sent).toEqual([{ type: "load" }]);
    act(() => first.emit({ type: "stage", stage: "runtime" }));
    expect(hook.result.current.status).toEqual({ state: "loading", stage: "runtime" });
    act(() => first.emit({ type: "ready" }));
    expect(hook.result.current.status).toEqual({ state: "ready" });
    return { hook, first };
  }

  it("collects one output per test", async () => {
    const { hook, first } = setup();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = hook.result.current.run("code", "f", TESTS, 2000);
    });
    expect(first.sent[1]).toMatchObject({ type: "run", code: "code", entry: "f" });
    act(() => {
      first.emit({ type: "started", index: 0 });
      first.emit({ type: "progress", index: 0, output: { json: "2" }, passed: true });
      first.emit({ type: "started", index: 1 });
      first.emit({ type: "progress", index: 1, output: { json: "4" }, passed: null });
      first.emit({ type: "result" });
    });
    await expect(done).resolves.toEqual({
      outputs: [{ json: "2" }, { json: "4" }],
      passed: [true, null],
    });
    expect(first.terminated).toBe(false);
  });

  it("terminates a test that never reports, times out the rest and restarts", async () => {
    const { hook, first } = setup();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = hook.result.current.run("while True: pass", "f", TESTS, 2000);
    });
    act(() => first.emit({ type: "started", index: 0 }));
    act(() => {
      vi.advanceTimersByTime(2000 + 200);
    });
    await expect(done).resolves.toEqual({
      outputs: [{ timeout: true }, { timeout: true }],
      passed: [null, null],
    });
    expect(first.terminated).toBe(true);
    const second = FakeWorker.all[1]!;
    expect(second.sent).toEqual([{ type: "load" }]);
    expect(hook.result.current.status.state).toBe("loading");
    act(() => second.emit({ type: "ready" }));
    expect(hook.result.current.status).toEqual({ state: "ready" });
  });

  it("keeps earlier outputs when a later test hangs", async () => {
    const { hook, first } = setup();
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = hook.result.current.run("code", "f", TESTS, 500);
    });
    act(() => {
      first.emit({ type: "started", index: 0 });
      first.emit({ type: "progress", index: 0, output: { json: "2" }, passed: true });
      first.emit({ type: "started", index: 1 });
      vi.advanceTimersByTime(700);
    });
    await expect(done).resolves.toEqual({
      outputs: [{ json: "2" }, { timeout: true }],
      passed: [true, null],
    });
  });

  it("reports a failed download and loads again on retry", () => {
    const { hook, first } = setup();
    act(() => first.emit({ type: "load_error", message: "offline" }));
    expect(hook.result.current.status).toEqual({ state: "error", message: "offline" });
    act(() => hook.result.current.retry());
    expect(FakeWorker.all).toHaveLength(2);
    expect(hook.result.current.status.state).toBe("loading");
  });
});

describe("Pyodide load failures (spec 015)", () => {
  it("are reported once per page session, without code", async () => {
    const observability = await import("@/lib/observability");
    const spy = vi.spyOn(observability, "reportOnce").mockImplementation(() => {});
    FakeWorker.all = [];
    const hook = renderHook(() => usePython(() => new FakeWorker()));
    act(() => FakeWorker.all[0]!.emit({ type: "load_error", message: "network" }));
    expect(hook.result.current.status).toEqual({ state: "error", message: "network" });
    expect(spy).toHaveBeenCalledWith("pyodide-load-error", "Python (Pyodide) failed to load");
  });
});
