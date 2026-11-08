import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Compass, Loader2, Pause } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AnswerForm } from "@/features/learn/AnswerForm";
import { type AnswerFields, conflictCode } from "@/features/learn/api";
import { ApiError } from "@/lib/api";
import type { DiagnosticState } from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

import {
  placementKeys,
  placementResultPath,
  startDiagnostic,
  submitDiagnosticAnswer,
  useAfterFinish,
  useDiagnostic,
  useDiagnosticQuestion,
} from "./api";

function Loading() {
  return (
    <div className="space-y-3 py-6" aria-busy="true">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-10 w-48" />
    </div>
  );
}

function Retry({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <AlertCircle className="size-8 text-muted-foreground" aria-hidden />
      <p>{text}</p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function Message({ text }: { text: string }) {
  return (
    <div className="space-y-4 py-8 text-center">
      <p>{text}</p>
      <Button asChild variant="outline">
        <Link to="/">Back home</Link>
      </Button>
    </div>
  );
}

function Intro({ diag, onStart }: { diag: DiagnosticState; onStart: () => Promise<void> }) {
  const [starting, setStarting] = useState(false);
  return (
    <div className="space-y-6 py-6">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/">
          <ArrowLeft aria-hidden />
          Home
        </Link>
      </Button>
      <div className="space-y-2">
        <Compass className="size-10 text-primary" aria-hidden />
        <h1 className="text-2xl font-semibold tracking-tight">
          Placement check{diag.course ? ` · ${diag.course.title}` : ""}
        </h1>
        <p className="text-lg">Up to {diag.max_questions} questions · no timer · no XP</p>
      </div>
      <ul className="list-disc space-y-1 pl-5">
        <li>It finds what you already know, so you can skip those lessons.</li>
        <li>You won&apos;t see right or wrong until the end. That&apos;s normal.</li>
        <li>Not sure? Press &quot;I don&apos;t know&quot;. There&apos;s no penalty for it.</li>
        <li>You can pause any time and carry on later.</li>
      </ul>
      <Button
        className="w-full sm:w-auto"
        disabled={starting}
        onClick={async () => {
          setStarting(true);
          try {
            await onStart();
          } catch {
            toast.error("Couldn't start, try again");
          } finally {
            setStarting(false);
          }
        }}
      >
        {starting && <Loader2 className="animate-spin" aria-hidden />}
        {diag.status === "active" ? "Continue" : "Start"}
      </Button>
    </div>
  );
}

function Active({
  diag,
  onFinished,
  onClosed,
}: {
  diag: DiagnosticState;
  onFinished: () => void;
  onClosed: () => void;
}) {
  const query = useDiagnosticQuestion(diag.id, true);
  const [submitting, setSubmitting] = useState(false);
  const shownAt = useRef(0);
  const promptId = useId();
  const navigate = useNavigate();
  const question = query.data;
  const closed = conflictCode(query.error) === "diagnostic_closed";

  useEffect(() => {
    shownAt.current = performance.now();
  }, [question?.position]);
  useEffect(() => {
    if (closed) onClosed();
  }, [closed, onClosed]);

  const submit = async (fields: AnswerFields | { idk: true }) => {
    if (!question?.session_id) return;
    setSubmitting(true);
    try {
      const saved = await submitDiagnosticAnswer(diag.id, {
        ...("idk" in fields ? { response: "", idk: true } : fields),
        position: question.position,
        session_id: question.session_id,
        time_taken_ms: Math.round(performance.now() - shownAt.current),
      });
      if (saved.finished) onFinished();
      else await query.refetch();
    } catch (error) {
      const code = conflictCode(error);
      if (code === "diagnostic_closed") onClosed();
      else if (code === "stale_question") await query.refetch();
      else toast.error("Couldn't save, try again");
    } finally {
      setSubmitting(false);
    }
  };

  if (query.isError && !closed) {
    return <Retry text="Couldn't load this question." onRetry={() => void query.refetch()} />;
  }
  if (!question || query.isFetching) return <Loading />;
  return (
    <div className="space-y-5 py-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold tracking-wide text-muted-foreground">
          Question {question.position} · at most {diag.max_questions}
        </p>
        <Button variant="ghost" size="sm" onClick={() => void navigate("/")}>
          <Pause aria-hidden />
          Pause
        </Button>
      </div>
      <div id={promptId}>
        <Markdown>{question.prompt_md}</Markdown>
      </div>
      <AnswerForm
        key={`${question.item_id}-${question.position}`}
        name={`placement-${question.position}`}
        part={{
          type:
            question.type === "numeric" || question.type === "mcq" ? question.type : "expression",
          unit: question.unit,
          unitRequired: !!question.unit_required,
          options: question.options,
          variables: question.variables,
        }}
        marked={null}
        submitting={submitting}
        labelledBy={promptId}
        onSubmit={(fields) => void submit(fields)}
      />
      <Button variant="outline" disabled={submitting} onClick={() => void submit({ idk: true })}>
        I don&apos;t know
      </Button>
    </div>
  );
}

/** `/placement/:id`: the placement diagnostic, one question at a time, without the app
 * navigation (spec 012). No right/wrong until the end. */
export function PlacementPage() {
  const { id = "" } = useParams();
  const state = useDiagnostic(id);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const afterFinish = useAfterFinish();

  const onFinished = () => {
    afterFinish();
    void navigate(placementResultPath(id), { replace: true });
  };
  const onClosed = () => void state.refetch();

  let body;
  if (state.isPending) {
    body = <Loading />;
  } else if (state.isError) {
    if (state.error instanceof ApiError && [403, 404].includes(state.error.status)) {
      return <NotFoundPage />;
    }
    body = (
      <Retry text="Couldn't load this placement check." onRetry={() => void state.refetch()} />
    );
  } else {
    const diag = state.data;
    if (diag.status === "cancelled") {
      body = <Message text="Your teacher cancelled this placement check." />;
    } else if (diag.status === "finished") {
      body = diag.empty ? (
        <Message text="Nothing to check right now. You can carry on learning as usual." />
      ) : (
        <div className="space-y-4 py-8 text-center">
          <p>You&apos;ve finished this placement check.</p>
          <Button asChild>
            <Link to={placementResultPath(diag.id)}>See your result</Link>
          </Button>
        </div>
      );
    } else if (diag.status === "sent") {
      body = (
        <Intro
          diag={diag}
          onStart={async () => {
            const started = await startDiagnostic(diag.id);
            queryClient.setQueryData(placementKeys.state(diag.id), started);
            void queryClient.invalidateQueries({ queryKey: placementKeys.current });
            if (started.status === "finished") afterFinish();
          }}
        />
      );
    } else {
      body = <Active diag={diag} onFinished={onFinished} onClosed={onClosed} />;
    }
  }
  return <main className="mx-auto min-h-svh max-w-prose px-4 pb-10">{body}</main>;
}
