import type { UseQueryResult } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type AnswerBody, conflictCode } from "@/features/learn/api";
import { QuestionStep } from "@/features/learn/QuestionStep";
import type { AnswerResult, Question } from "@/lib/types";

/** Serves a session's questions one at a time: load, submit, show the result, then the next one.
 * A 409 on load is a panel (`renderConflict`), not an error toast. */
export function PracticeRunner({
  header,
  query,
  submit,
  preview = false,
  assetBase,
  onDone,
  renderConflict,
}: {
  header: string;
  query: UseQueryResult<Question, unknown>;
  submit: (body: AnswerBody) => Promise<AnswerResult>;
  preview?: boolean;
  assetBase?: string;
  /** Continue after the session passed or failed. */
  onDone: (result: AnswerResult) => void;
  renderConflict?: (code: string, error: unknown) => ReactNode;
}) {
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const shownAt = useRef(0);
  const question = query.data;

  useEffect(() => {
    shownAt.current = performance.now();
  }, [question?.item_id, question?.position, query.dataUpdatedAt]);

  if (query.isError) {
    const code = conflictCode(query.error);
    if (code && renderConflict) return <>{renderConflict(code, query.error)}</>;
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <AlertCircle className="size-8 text-muted-foreground" aria-hidden />
        <p>Couldn&apos;t load this question.</p>
        <Button variant="outline" onClick={() => query.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  if (!question || advancing || (query.isFetching && result === null && !query.isFetched)) {
    return (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-10 w-48" />
      </div>
    );
  }

  const onSubmit = async (response: string) => {
    setSubmitting(true);
    try {
      const body: AnswerBody = {
        position: question.position,
        response,
        time_taken_ms: Math.round(performance.now() - shownAt.current),
      };
      if (preview) {
        body.item_id = question.item_id;
        body.seed = question.preview_seed;
      }
      setResult(await submit(body));
    } catch {
      toast.error("Couldn't submit, try again");
    } finally {
      setSubmitting(false);
    }
  };

  const onNext = async () => {
    setAdvancing(true);
    setResult(null);
    try {
      await query.refetch();
    } finally {
      setAdvancing(false);
    }
  };

  return (
    <QuestionStep
      key={`${question.item_id}-${question.position}-${query.dataUpdatedAt}`}
      header={header}
      question={question}
      result={result}
      submitting={submitting}
      preview={preview}
      assetBase={assetBase}
      onSubmit={onSubmit}
      onNext={onNext}
      onContinue={() => result && onDone(result)}
    />
  );
}
