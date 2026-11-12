/** Messages between the page and the Pyodide worker (spec 006). */
import type { TestOutput } from "@/lib/types";

export { PYODIDE_URL, PYODIDE_VERSION } from "./pyodideVersion";

export type LoadStage = "script" | "runtime" | "setup";

/** A test as the worker runs it. `args` / `expected` are JSON text. */
export type RunTest = {
  visible: boolean;
  returns: "value" | "stdout";
  args: string;
  stdin: string | null;
  expected?: string | null;
  expected_stdout?: string | null;
};

export type WorkerIn =
  { type: "load" } | { type: "run"; code: string; entry: string; tests: RunTest[] };

export type WorkerOut =
  | { type: "stage"; stage: LoadStage }
  | { type: "ready" }
  | { type: "load_error"; message: string }
  | { type: "started"; index: number }
  | { type: "progress"; index: number; output: TestOutput; passed: boolean | null }
  | { type: "result" };
