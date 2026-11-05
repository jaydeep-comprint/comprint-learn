import { CheckCircle2, Clock, Loader2, Play, RotateCcw, XCircle } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import type { AnswerFields } from "@/features/learn/api";
import type { CodePublic, CodeTestResult, TestOutput } from "@/lib/types";
import { cn } from "@/lib/utils";

import { CodeEditor } from "./CodeEditor";
import { callText } from "./format";
import type { LoadStage, RunTest } from "./protocol";
import { type PythonStatus, usePython } from "./usePython";

const STAGES: Record<LoadStage, { label: string; value: number }> = {
  script: { label: "Downloading Python…", value: 20 },
  runtime: { label: "Starting Python…", value: 60 },
  setup: { label: "Getting ready…", value: 90 },
};

function outputText(output: TestOutput | undefined, limitMs: number): string {
  if (!output) return "";
  if ("timeout" in output) return `Took too long (over ${limitMs / 1000} s)`;
  if ("error" in output) return output.error;
  if ("stdout" in output) return output.stdout;
  return output.json;
}

type Row = {
  index: number;
  visible: boolean;
  status: "passed" | "failed" | "error" | "timeout";
  input: string;
  stdin: string | null;
  expected: string | null;
  got: string;
};

function runRows(code: CodePublic, outputs: TestOutput[], passed: (boolean | null)[]): Row[] {
  const visible = code.tests.filter((t) => t.visible);
  return visible.map((t, i) => {
    const output = outputs[i];
    const status =
      output && "timeout" in output
        ? "timeout"
        : output && "error" in output
          ? "error"
          : passed[i]
            ? "passed"
            : "failed";
    return {
      index: i,
      visible: true,
      status,
      input: callText(code.entry, t.args),
      stdin: t.stdin,
      expected: t.returns === "stdout" ? t.expected_stdout : t.expected,
      got: outputText(output, code.time_limit_ms),
    };
  });
}

function submitRows(code: CodePublic, tests: CodeTestResult[]): Row[] {
  return tests.map((t, i) => ({
    index: i,
    visible: t.visible,
    status: t.status,
    input: callText(code.entry, t.args),
    stdin: t.stdin,
    expected: t.visible ? t.expected : null,
    got: t.status === "timeout" ? `Took too long (over ${code.time_limit_ms / 1000} s)` : t.got,
  }));
}

function StatusIcon({ status }: { status: Row["status"] }) {
  if (status === "passed")
    return <CheckCircle2 className="size-4 shrink-0 text-[var(--success)]" aria-label="Passed" />;
  if (status === "timeout")
    return <Clock className="size-4 shrink-0 text-destructive" aria-label="Took too long" />;
  return <XCircle className="size-4 shrink-0 text-destructive" aria-label="Failed" />;
}

/** One row per test. Hidden tests never show an expected value. */
export function TestResults({ rows }: { rows: Row[] }) {
  let hidden = 0;
  let shown = 0;
  return (
    <ul className="space-y-2" data-testid="test-results">
      {rows.map((row) => {
        const name = row.visible ? `Test ${++shown}` : `Hidden test ${++hidden}`;
        return (
          <li
            key={row.index}
            className={cn(
              "space-y-1 rounded-md border p-3 text-sm",
              row.status === "passed" ? "border-[var(--success)]/40" : "border-destructive/40",
            )}
            data-testid={row.visible ? "visible-test" : "hidden-test"}
          >
            <p className="flex items-center gap-2 font-medium">
              <StatusIcon status={row.status} />
              {name}
            </p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-xs">
              <dt className="text-muted-foreground">Input</dt>
              <dd className="break-all whitespace-pre-wrap">{row.input}</dd>
              {row.stdin && (
                <>
                  <dt className="text-muted-foreground">Typed in</dt>
                  <dd className="break-all whitespace-pre-wrap">{row.stdin}</dd>
                </>
              )}
              {row.visible && row.expected !== null && (
                <>
                  <dt className="text-muted-foreground">Expected</dt>
                  <dd className="break-all whitespace-pre-wrap">{row.expected}</dd>
                </>
              )}
              <dt className="text-muted-foreground">Got</dt>
              <dd className="max-h-40 overflow-auto break-all whitespace-pre-wrap">{row.got}</dd>
            </dl>
            {!row.visible && row.status === "failed" && (
              <p className="text-xs">Your result differs from the expected one.</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Loading({ status, onRetry }: { status: PythonStatus; onRetry: () => void }) {
  if (status.state === "error") {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border p-3 text-sm">
        <span>Couldn&apos;t load Python. Check your connection.</span>
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RotateCcw aria-hidden /> Retry
        </Button>
      </div>
    );
  }
  if (status.state !== "loading") return null;
  const stage = STAGES[status.stage];
  return (
    <div className="space-y-1" role="status" aria-live="polite">
      <p className="text-sm text-muted-foreground">Loading Python… {stage.label}</p>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="Loading Python"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={stage.value}
      >
        <div className="h-full bg-primary transition-all" style={{ width: `${stage.value}%` }} />
      </div>
    </div>
  );
}

function isPhone(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(max-width: 767px)").matches;
}

/** A Python task: editor, Run (visible tests, never sent), Submit (every test's output goes to
 * the server, which compares with the expected values only it has), and the results. */
export function CodeQuestion({
  code,
  hasResult,
  serverTests,
  submitting,
  onSubmit,
  onDraftChange,
}: {
  code: CodePublic;
  /** Answered: the editor is read-only and Run/Submit are gone. */
  hasResult: boolean;
  serverTests: CodeTestResult[] | null;
  submitting: boolean;
  onSubmit: (fields: AnswerFields) => void;
  /** The editor contents, for the AI tutor (spec 009). */
  onDraftChange?: (draft: string | null) => void;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const python = usePython();
  const [source, setSource] = useState(code.prefill ?? code.starter);
  useEffect(() => {
    onDraftChange?.(source);
  }, [source, onDraftChange]);
  const [runResult, setRunResult] = useState<Row[] | null>(null);
  const [phase, setPhase] = useState<"idle" | "running" | "submitting">("idle");
  const ready = python.status.state === "ready";
  const busy = phase !== "idle" || submitting;
  const tests: RunTest[] = code.tests;

  const onRun = async () => {
    if (!ready || busy || hasResult) return;
    setPhase("running");
    try {
      const visible = tests.filter((t) => t.visible);
      const out = await python.run(source, code.entry, visible, code.time_limit_ms);
      setRunResult(runRows(code, out.outputs, out.passed));
    } finally {
      setPhase("idle");
    }
  };

  const onSubmitClick = async () => {
    if (!ready || busy || hasResult) return;
    setPhase("submitting");
    try {
      const out = await python.run(source, code.entry, tests, code.time_limit_ms);
      onSubmit({ code: source, outputs: out.outputs });
    } finally {
      setPhase("idle");
    }
  };

  const rows = serverTests ? submitRows(code, serverTests) : runResult;
  return (
    <div className="space-y-3">
      {isPhone() && (
        <p className="rounded-md bg-muted px-3 py-2 text-sm">
          Tip: this is easier on a computer or tablet.
        </p>
      )}
      <CodeEditor
        key={hasResult ? "done" : "editing"}
        value={source}
        onChange={setSource}
        onRun={onRun}
        readOnly={hasResult}
        describedBy={hintId}
      />
      <p id={hintId} className="text-xs text-muted-foreground">
        Tab indents. To leave the editor, press Esc then Tab. Ctrl+Enter (⌘+Enter) runs.
      </p>
      <Loading status={python.status} onRetry={python.retry} />
      {!hasResult && (
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={onRun} disabled={!ready || busy}>
            {phase === "running" ? (
              <Loader2 className="animate-spin" aria-hidden />
            ) : (
              <Play aria-hidden />
            )}
            Run
          </Button>
          <Button type="button" onClick={onSubmitClick} disabled={!ready || busy}>
            {(phase === "submitting" || submitting) && (
              <Loader2 className="animate-spin" aria-hidden />
            )}
            {phase === "submitting" ? "Running tests…" : submitting ? "Checking…" : "Submit"}
          </Button>
        </div>
      )}
      {rows && rows.length > 0 && <TestResults rows={rows} />}
    </div>
  );
}
