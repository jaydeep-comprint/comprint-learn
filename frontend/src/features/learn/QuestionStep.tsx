import { CheckCircle2, XCircle } from "lucide-react";
import { lazy, Suspense, useId } from "react";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { AnswerFields } from "@/features/learn/api";
import { AnswerForm } from "@/features/learn/AnswerForm";
import { MultistepQuestion } from "@/features/learn/MultistepQuestion";
import { ResultPanel } from "@/features/learn/ResultPanel";
import type { AnswerResult, Question } from "@/lib/types";
import { cn } from "@/lib/utils";

// CodeMirror and the Python runner load only when a code question appears.
const CodeQuestion = lazy(() =>
  import("@/features/code/CodeQuestion").then((m) => ({ default: m.CodeQuestion })),
);

/** This session's answers: green/red dots, the current question hollow. */
function Dots({ results, pending }: { results: boolean[]; pending: boolean }) {
  const right = results.filter(Boolean).length;
  return (
    <div
      className="flex items-center gap-1.5"
      role="img"
      aria-label={`${right} of ${results.length} correct so far`}
    >
      {results.map((ok, i) => (
        <span
          key={i}
          className={cn("size-3 rounded-full", ok ? "bg-[var(--success)]" : "bg-destructive")}
          data-testid={ok ? "dot-correct" : "dot-wrong"}
        />
      ))}
      {pending && (
        <span
          className="size-3 rounded-full border-2 border-muted-foreground"
          data-testid="dot-current"
        />
      )}
    </div>
  );
}

/** After a code Submit: all passed or how many, then (when earned) the reference solution and
 * the explanation. */
function CodeSummary({ result, assetBase }: { result: AnswerResult; assetBase?: string }) {
  const tests = result.tests ?? [];
  const passed = tests.filter((t) => t.passed).length;
  return (
    <div role="status" className="space-y-2 rounded-lg border p-4">
      <p className="flex items-center gap-2 font-semibold">
        {result.correct ? (
          <CheckCircle2 className="size-5 text-[var(--success)]" aria-hidden />
        ) : (
          <XCircle className="size-5 text-destructive" aria-hidden />
        )}
        {result.correct
          ? "All tests passed ✓"
          : `Not quite: ${passed} of ${tests.length} tests passed`}
      </p>
      {result.solution && (
        <details className="space-y-2" open>
          <summary className="cursor-pointer font-medium">A reference solution</summary>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-sm" data-testid="solution">
            <code>{result.solution}</code>
          </pre>
        </details>
      )}
      {result.explanation_md && <Markdown assetBase={assetBase}>{result.explanation_md}</Markdown>}
    </div>
  );
}

/** One question: prompt, input, submit; then the result and what comes next.
 *
 * Every format (spec 006): numeric (with a unit box), expression and MCQ; multi-step problems one
 * step at a time; Python code with Run and Submit. Remount it (`key`) for each new question so the
 * input starts empty. `preview` (staff) shows "Another question" instead of dots and pass/fail. */
export function QuestionStep({
  header,
  question,
  result,
  submitting,
  preview = false,
  assetBase,
  onSubmit,
  onNext,
  onContinue,
  passedLabel = "Part passed ✓",
  continueLabel,
}: {
  header: string;
  question: Question;
  result: AnswerResult | null;
  submitting: boolean;
  preview?: boolean;
  assetBase?: string;
  onSubmit: (fields: AnswerFields) => void;
  /** Next question (active session) or, for staff, another question. */
  onNext: () => void;
  /** After the session passed or failed. */
  onContinue: () => void;
  passedLabel?: string;
  /** The button after the session ended (default "Continue"). */
  continueLabel?: (result: AnswerResult) => string;
}) {
  const id = useId();
  const promptId = `${id}-prompt`;
  const done = result !== null && (result.item_done ?? true);
  const status = done ? result.session_status : "active";
  const results = result?.results ?? question.results;
  const quick = question.type !== "multistep" && question.type !== "code";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold tracking-wide text-muted-foreground">{header}</p>
        {!preview && <Dots results={results} pending={!done} />}
      </div>
      <div id={promptId}>
        <Markdown assetBase={assetBase}>{question.prompt_md}</Markdown>
      </div>
      {question.type === "multistep" ? (
        <MultistepQuestion
          question={question}
          result={result}
          submitting={submitting}
          assetBase={assetBase}
          onSubmit={onSubmit}
        />
      ) : question.type === "code" && question.code ? (
        <Suspense fallback={<Skeleton className="h-64 w-full" />}>
          <CodeQuestion
            code={question.code}
            hasResult={result !== null}
            serverTests={result?.tests ?? null}
            submitting={submitting}
            onSubmit={onSubmit}
          />
        </Suspense>
      ) : (
        <AnswerForm
          name={`q-${question.item_id}-${question.position}`}
          part={{
            type:
              question.type === "numeric" || question.type === "mcq" ? question.type : "expression",
            unit: question.unit,
            unitRequired: !!question.unit_required,
            options: question.options,
            variables: question.variables,
          }}
          marked={result}
          submitting={submitting}
          labelledBy={promptId}
          onSubmit={onSubmit}
        />
      )}
      {result && done && (
        <>
          {quick && <ResultPanel question={question} result={result} assetBase={assetBase} />}
          {question.type === "code" && <CodeSummary result={result} assetBase={assetBase} />}
          {preview ? (
            <Button onClick={onNext} className="w-full sm:w-auto">
              Another question
            </Button>
          ) : status === "active" ? (
            <Button onClick={onNext} className="w-full sm:w-auto">
              Next question
            </Button>
          ) : (
            <div className="space-y-3">
              {status === "passed" && (
                <p className="flex items-center gap-2 rounded-md bg-[var(--success)]/10 px-3 py-2 font-medium">
                  <CheckCircle2 className="size-5 text-[var(--success)]" aria-hidden />
                  {passedLabel}
                </p>
              )}
              <Button onClick={onContinue} className="w-full sm:w-auto">
                {continueLabel?.(result) ?? "Continue"}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
