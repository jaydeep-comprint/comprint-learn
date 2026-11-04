/// <reference lib="webworker" />
/**
 * Runs students' Python in Pyodide, off the main thread (spec 006).
 *
 * Messages in:  `{type: "load"}`, then `{type: "run", code, entry, tests, time_limit_ms}`.
 * Messages out: `stage` while loading, `ready` | `load_error`; per run: `started {index}` before
 * each test (the main thread's watchdog times it), `progress {index, output, passed}` after it,
 * then `result`. An infinite loop never returns, so the main thread terminates this worker.
 *
 * Outputs carry return values as JSON text made by Python (`json.dumps`), so `1`, `1.0` and `True`
 * stay distinct all the way to the server. Not a security boundary: the server never trusts the
 * pass/fail computed here (ARCHITECTURE decision 6).
 */
import compareSource from "./compare.py?raw";
import { PYODIDE_URL, type RunTest, type WorkerIn, type WorkerOut } from "./protocol";

type Pyodide = {
  runPython: (code: string) => unknown;
  globals: { set: (name: string, value: unknown) => void };
};

const ctx = self as unknown as DedicatedWorkerGlobalScope;
let pyodide: Pyodide | null = null;

function post(message: WorkerOut) {
  ctx.postMessage(message);
}

// Helpers defined once in the Python runtime. User code runs with its own builtins whose
// `__import__` refuses the JS bridge and the package installer.
const SETUP = String.raw`
import builtins, contextlib, io, json, math, sys

MAX_OUTPUT = 10_000
TRUNCATED = "(output truncated)"
_BANNED = {"js", "pyodide", "pyodide_js", "micropip", "_pyodide"}
_real_import = builtins.__import__


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] in _BANNED:
        raise ImportError("That module isn't available here")
    return _real_import(name, globals, locals, fromlist, level)


_user_builtins = dict(builtins.__dict__)
_user_builtins["__import__"] = _guarded_import


class _Capped(io.StringIO):
    def __init__(self):
        super().__init__()
        self.cut = False

    def write(self, s):
        room = MAX_OUTPUT - self.tell()
        if room <= 0:
            self.cut = True
            return len(s)
        if len(s) > room:
            self.cut = True
            super().write(s[:room])
            return len(s)
        return super().write(s)

    def text(self):
        out = self.getvalue()
        return out + "\n" + TRUNCATED if self.cut else out


_ns = {}


def _define(code):
    global _ns
    _ns = {"__name__": "__main__", "__builtins__": _user_builtins}
    try:
        with contextlib.redirect_stdout(_Capped()):
            exec(compile(code, "main.py", "exec"), _ns)
    except BaseException as exc:
        return json.dumps({"error": f"defining the code raised {type(exc).__name__}: {exc}"})
    return ""


def _run(entry, args_json, stdin, returns):
    fn = _ns.get(entry)
    if not callable(fn):
        return json.dumps({"error": f"doesn't define a function {entry}()"})
    out = _Capped()
    sys.stdin = io.StringIO(stdin or "")
    try:
        with contextlib.redirect_stdout(out):
            got = fn(*json.loads(args_json))
    except BaseException as exc:
        return json.dumps({"error": f"raised {type(exc).__name__}: {exc}"})
    finally:
        sys.stdin = sys.__stdin__
    if returns == "stdout":
        return json.dumps({"stdout": out.text()})
    try:
        text = json.dumps(got, allow_nan=False)
    except (TypeError, ValueError):
        return json.dumps({"error": "returned a value that can't be compared"})
    if len(text) > MAX_OUTPUT:
        return json.dumps({"error": "returned a value that's too large to compare"})
    return json.dumps({"json": text})


def _passes(output_json, expected, expected_stdout):
    """Run's check of a visible test, with the server's comparison (compare.py)."""
    output = json.loads(output_json)
    if expected_stdout is not None:
        return "stdout" in output and lines(output["stdout"]) == lines(expected_stdout)
    if expected is None or "json" not in output:
        return False
    return same(json.loads(output["json"]), json.loads(expected))
`;

async function load() {
  try {
    post({ type: "stage", stage: "script" });
    const mod = (await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)) as {
      loadPyodide: (opts: { indexURL: string }) => Promise<Pyodide>;
    };
    post({ type: "stage", stage: "runtime" });
    const py = await mod.loadPyodide({ indexURL: PYODIDE_URL });
    post({ type: "stage", stage: "setup" });
    py.runPython(compareSource);
    py.runPython(SETUP);
    pyodide = py;
    post({ type: "ready" });
  } catch (error) {
    post({ type: "load_error", message: error instanceof Error ? error.message : String(error) });
  }
}

function call(py: Pyodide, expression: string, args: Record<string, unknown>): string {
  for (const [name, value] of Object.entries(args)) py.globals.set(name, value);
  return String(py.runPython(expression));
}

function run(code: string, entry: string, tests: RunTest[]) {
  const py = pyodide;
  if (!py) {
    post({ type: "load_error", message: "Python isn't loaded" });
    return;
  }
  post({ type: "started", index: 0 });
  const defined = call(py, "_define(_code)", { _code: code });
  tests.forEach((test, index) => {
    if (index > 0) post({ type: "started", index });
    const output =
      defined ||
      call(py, "_run(_entry, _args, _stdin, _returns)", {
        _entry: entry,
        _args: test.args,
        _stdin: test.stdin ?? "",
        _returns: test.returns,
      });
    let passed: boolean | null = null;
    if (test.visible) {
      passed =
        call(py, "str(_passes(_out, _expected, _expected_stdout))", {
          _out: output,
          _expected: test.expected ?? null,
          _expected_stdout: test.expected_stdout ?? null,
        }) === "True";
    }
    post({ type: "progress", index, output: JSON.parse(output), passed });
  });
  post({ type: "result" });
}

ctx.onmessage = (event: MessageEvent<WorkerIn>) => {
  const message = event.data;
  if (message.type === "load") void load();
  else if (message.type === "run") run(message.code, message.entry, message.tests);
};
