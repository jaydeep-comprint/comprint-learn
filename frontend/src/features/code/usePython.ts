import { useCallback, useEffect, useRef, useState } from "react";

import { reportOnce } from "@/lib/observability";
import type { TestOutput } from "@/lib/types";

import type { LoadStage, RunTest, WorkerIn, WorkerOut } from "./protocol";

export type PythonStatus =
  | { state: "loading"; stage: LoadStage }
  | { state: "ready" }
  | { state: "running"; index: number; total: number }
  | { state: "error"; message: string };

export type RunResult = {
  /** One per test, in the order given. */
  outputs: TestOutput[];
  /** Visible tests: the browser's own check (Run only; the server decides on Submit). */
  passed: (boolean | null)[];
};

/** The subset of `Worker` used here, so tests can pass a fake. */
export type WorkerLike = {
  postMessage: (message: WorkerIn) => void;
  terminate: () => void;
  onmessage: ((event: MessageEvent<WorkerOut>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
};

export type WorkerFactory = () => WorkerLike;

export const defaultWorkerFactory: WorkerFactory = () =>
  new Worker(new URL("./pyodideWorker.ts", import.meta.url), {
    type: "module",
  }) as unknown as WorkerLike;

/** Grace on top of the item's limit for posting messages between threads. */
const WATCHDOG_SLACK_MS = 100;
const CRASHED = "Python stopped unexpectedly";

type Pending = {
  tests: RunTest[];
  outputs: (TestOutput | undefined)[];
  passed: (boolean | null)[];
  limitMs: number;
  resolve: (result: RunResult) => void;
};

/** One Pyodide worker per mounted question: loads it, runs code against tests one at a time with
 * a watchdog per test (an infinite loop terminates the worker, marks that test and the rest
 * `timeout`, and starts a fresh one), and reloads on Retry after a failed download. */
export function usePython(factory: WorkerFactory = defaultWorkerFactory) {
  const [status, setStatus] = useState<PythonStatus>({ state: "loading", stage: "script" });
  const worker = useRef<WorkerLike | null>(null);
  const pending = useRef<Pending | null>(null);
  const watchdog = useRef<ReturnType<typeof setTimeout> | null>(null);
  const factoryRef = useRef(factory);
  // `start` restarts itself (after a timeout or crash): call it through a ref.
  const restart = useRef<() => void>(() => {});

  const clearWatchdog = () => {
    if (watchdog.current !== null) clearTimeout(watchdog.current);
    watchdog.current = null;
  };

  const finish = useCallback((fill: TestOutput) => {
    const run = pending.current;
    if (!run) return;
    pending.current = null;
    clearWatchdog();
    run.resolve({
      outputs: run.outputs.map((o) => o ?? fill),
      passed: run.passed,
    });
  }, []);

  const start = useCallback(() => {
    worker.current?.terminate();
    const w = factoryRef.current();
    worker.current = w;
    w.onmessage = (event) => {
      if (worker.current !== w) return; // a worker we already replaced
      const message = event.data;
      const run = pending.current;
      switch (message.type) {
        case "stage":
          setStatus({ state: "loading", stage: message.stage });
          break;
        case "ready":
          setStatus({ state: "ready" });
          break;
        case "load_error":
          // Spec 015: a failed Pyodide load is a fault (blocked CDN, old browser); report it
          // once per page session, never with the student's code. Student code errors are
          // results (`progress` outputs), never reported.
          reportOnce("pyodide-load-error", "Python (Pyodide) failed to load");
          setStatus({ state: "error", message: message.message });
          finish({ error: CRASHED });
          break;
        case "started":
          if (!run) break;
          setStatus({ state: "running", index: message.index, total: run.tests.length });
          clearWatchdog();
          watchdog.current = setTimeout(() => {
            // An infinite loop: this test and every test not yet run time out.
            finish({ timeout: true });
            restart.current();
          }, run.limitMs + WATCHDOG_SLACK_MS);
          break;
        case "progress":
          if (!run) break;
          run.outputs[message.index] = message.output;
          run.passed[message.index] = message.passed;
          break;
        case "result":
          clearWatchdog();
          setStatus({ state: "ready" });
          finish({ error: CRASHED });
          break;
      }
    };
    w.onerror = () => {
      if (worker.current !== w) return;
      const running = pending.current !== null;
      finish({ error: CRASHED });
      if (running) restart.current();
      else setStatus({ state: "error", message: CRASHED });
    };
    w.postMessage({ type: "load" });
  }, [finish]);

  useEffect(() => {
    // Restarts (timeout, crash, Retry) show the loading state again; the first load starts in it.
    restart.current = () => {
      setStatus({ state: "loading", stage: "script" });
      start();
    };
    start();
    return () => {
      clearWatchdog();
      worker.current?.terminate();
      worker.current = null;
    };
  }, [start]);

  const run = useCallback(
    (code: string, entry: string, tests: RunTest[], limitMs: number) =>
      new Promise<RunResult>((resolve) => {
        const w = worker.current;
        if (!w || pending.current) {
          resolve({
            outputs: tests.map(() => ({ error: CRASHED })),
            passed: tests.map(() => null),
          });
          return;
        }
        pending.current = {
          tests,
          outputs: tests.map(() => undefined),
          passed: tests.map(() => null),
          limitMs,
          resolve,
        };
        setStatus({ state: "running", index: 0, total: tests.length });
        w.postMessage({ type: "run", code, entry, tests });
      }),
    [],
  );

  const retry = useCallback(() => restart.current(), []);
  return { status, run, retry };
}
