import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Lightbulb, Loader2, Send, X } from "lucide-react";
import { type RefObject, useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { conceptCourse, lessonPath } from "@/features/learn/paths";
import {
  MAX_DRAFT,
  MAX_MESSAGE,
  RUNG_NAMES,
  requestHint,
  sendMessage,
  tutorKeys,
  useTutorThread,
} from "@/features/tutor/api";
import { ApiError } from "@/lib/api";
import type { TutorMessage, TutorReply, TutorThread } from "@/lib/types";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { cn } from "@/lib/utils";

type Problem = "unavailable" | "daily" | "closed" | null;
type Action = { kind: "hint" } | { kind: "chat"; text: string };

const DAILY_MESSAGE = "You've used today's 20 tutor messages. They come back at midnight.";
const UNAVAILABLE_MESSAGE = "The tutor isn't available right now. Try again in a minute.";
const CLOSED_MESSAGE = "This question has finished.";
const EMPTY_MESSAGE =
  "Stuck? A hint points you to the worked example, a prerequisite, or something to try. Chat is for questions about the wording.";

function Bubble({ message }: { message: TutorMessage }) {
  if (message.role === "student") {
    return (
      <li className="flex justify-end">
        <p className="max-w-[85%] rounded-lg rounded-br-sm bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">
          {message.kind === "hint" ? `Hint ${message.rung ?? ""} please` : message.text}
        </p>
      </li>
    );
  }
  return (
    <li className="flex justify-start">
      <div className="max-w-[85%] space-y-1 rounded-lg rounded-bl-sm bg-muted px-3 py-2 text-sm">
        {message.kind === "hint" && message.rung && (
          <p className="flex items-center gap-1 text-xs font-semibold text-muted-foreground">
            <Lightbulb className="size-3.5" aria-hidden />
            Hint {message.rung} · {RUNG_NAMES[message.rung]}
          </p>
        )}
        {message.text === null ? (
          <p className="text-muted-foreground italic">This message was removed.</p>
        ) : (
          <Markdown>{message.text}</Markdown>
        )}
        {message.link && (
          <Button asChild variant="outline" size="sm" className="mt-1">
            <a
              href={lessonPath(conceptCourse(message.link.id), message.link.id)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open {message.link.title}
              <ExternalLink className="size-3.5" aria-hidden />
            </a>
          </Button>
        )}
      </div>
    </li>
  );
}

function problemFrom(error: unknown): Problem | "refetch" | "busy" | "other" {
  if (!(error instanceof ApiError)) return "other";
  if (error.status === 429) return "daily";
  if (error.status === 503) return "unavailable";
  if (error.code === "session_closed") return "closed";
  if (error.code === "tutor_busy") return "busy";
  if (error.status === 409) return "refetch"; // caps, question answered meanwhile
  return "other";
}

/** The tutor's contents: messages, Hint button, chat box and limits. */
export function TutorBody({
  sessionId,
  position,
  draft,
}: {
  sessionId: string;
  position: number;
  /** The current answer draft (sent with each request; never MCQ picks). */
  draft: RefObject<string | null>;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const query = useTutorThread(sessionId, position);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Action | null>(null);
  const [problem, setProblem] = useState<Problem>(null);
  const [lastAction, setLastAction] = useState<Action | null>(null);
  const listEnd = useRef<HTMLLIElement>(null);
  const thread = query.data;

  useEffect(() => {
    listEnd.current?.scrollIntoView?.({ block: "nearest" });
  }, [thread?.messages.length, pending]);

  if (!thread) {
    return query.isError ? (
      <p className="text-sm">{UNAVAILABLE_MESSAGE}</p>
    ) : (
      <Loader2 className="mx-auto size-5 animate-spin" aria-label="Loading" />
    );
  }

  const after = thread.mode === "after";
  const closed = thread.closed || problem === "closed";
  const daily = thread.daily_left <= 0 || problem === "daily";
  const busy = pending !== null;
  const blocked = closed || daily;

  const run = async (action: Action) => {
    setPending(action);
    setLastAction(action);
    setProblem(null);
    const current = draft.current ? draft.current.slice(0, MAX_DRAFT) : null;
    try {
      const reply: TutorReply =
        action.kind === "hint"
          ? await requestHint(sessionId, position, current)
          : await sendMessage(sessionId, position, action.text, current);
      queryClient.setQueryData<TutorThread>(tutorKeys.thread(sessionId, position), reply.thread);
      if (action.kind === "chat") setText("");
    } catch (error) {
      const kind = problemFrom(error);
      if (kind === "daily" || kind === "unavailable" || kind === "closed") setProblem(kind);
      else if (kind === "busy") toast.info("The tutor is still answering.");
      else if (kind === "refetch") void query.refetch();
      else
        toast.error(
          error instanceof ApiError && error.message ? error.message : "Couldn't send, try again",
        );
    } finally {
      setPending(null);
    }
  };

  const onSend = () => {
    const trimmed = text.trim();
    if (!trimmed || busy || blocked || thread.chat_left <= 0) return;
    void run({ kind: "chat", text: trimmed });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Your teacher can read this chat. Don&apos;t share personal details.
      </p>
      {after && <p className="text-xs font-semibold">No XP cost</p>}
      <ul
        className="min-h-24 flex-1 space-y-2 overflow-y-auto"
        aria-live="polite"
        aria-label="Tutor messages"
      >
        {thread.messages.length === 0 && !busy && (
          <li className="text-sm text-muted-foreground">{EMPTY_MESSAGE}</li>
        )}
        {thread.messages.map((m) => (
          <Bubble key={m.id} message={m} />
        ))}
        {busy && (
          <li className="flex justify-start">
            <p className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Tutor is thinking…
            </p>
          </li>
        )}
        <li ref={listEnd} aria-hidden className="h-0" />
      </ul>

      {problem === "unavailable" && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm"
        >
          <span className="flex-1">{UNAVAILABLE_MESSAGE}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => lastAction && void run(lastAction)}
            disabled={busy}
          >
            Retry
          </Button>
        </div>
      )}
      {daily && (
        <p role="alert" className="rounded-md border p-2 text-sm">
          {DAILY_MESSAGE}
        </p>
      )}
      {closed && (
        <p role="alert" className="rounded-md border p-2 text-sm">
          {CLOSED_MESSAGE}
        </p>
      )}

      {!after && (
        <Button
          variant="outline"
          onClick={() => void run({ kind: "hint" })}
          disabled={busy || blocked || thread.next_rung === null}
          className="h-auto w-full py-2 whitespace-normal"
        >
          <Lightbulb aria-hidden />
          {thread.next_rung === null
            ? "No hints left"
            : `Hint ${thread.next_rung} of 3 · lowers this session's XP by 25%`}
        </Button>
      )}

      <form
        className="space-y-1"
        onSubmit={(e) => {
          e.preventDefault();
          onSend();
        }}
      >
        <label htmlFor={`${id}-chat`} className="sr-only">
          Message the tutor
        </label>
        <div className="flex items-end gap-2">
          <Textarea
            id={`${id}-chat`}
            value={text}
            maxLength={MAX_MESSAGE}
            rows={2}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder={
              after ? "Ask why your answer was wrong…" : "Ask what a word or symbol means…"
            }
            disabled={blocked || thread.chat_left <= 0}
            className="max-h-32 min-h-10"
          />
          <Button
            type="submit"
            size="icon"
            aria-label="Send"
            disabled={busy || blocked || !text.trim() || thread.chat_left <= 0}
          >
            <Send aria-hidden />
          </Button>
        </div>
        <div className="flex justify-between gap-2 text-xs text-muted-foreground">
          <span>
            {thread.chat_left <= 0
              ? "No more chat on this question"
              : `${Math.max(0, thread.daily_left)} tutor messages left today`}
          </span>
          {text.length > 400 && (
            <span>
              {text.length}/{MAX_MESSAGE}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

/** Desktop (≥ 1024 px): a right-hand panel, the question stays visible. Smaller: a bottom sheet. */
export function TutorPanel({
  open,
  onClose,
  sessionId,
  position,
  draft,
}: {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  position: number;
  draft: RefObject<string | null>;
}) {
  const desktop = useMediaQuery("(min-width: 1024px)");
  const body = <TutorBody sessionId={sessionId} position={position} draft={draft} />;
  if (desktop) {
    if (!open) return null;
    return (
      <aside
        aria-label="Tutor"
        className="fixed top-20 right-4 bottom-4 z-30 flex w-96 flex-col gap-3 rounded-lg border bg-background p-4 shadow-lg"
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">Tutor</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close tutor">
            <X aria-hidden />
          </Button>
        </div>
        {body}
      </aside>
    );
  }
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} modal={false}>
      <SheetContent side="bottom" className={cn("flex max-h-[75dvh] flex-col gap-3 p-4 pb-6")}>
        <div
          aria-hidden
          className="mx-auto h-1.5 w-10 shrink-0 rounded-full bg-muted-foreground/30"
        />
        <SheetTitle className="pr-8">Tutor</SheetTitle>
        <SheetDescription className="sr-only">
          Hints and questions about this question
        </SheetDescription>
        {body}
      </SheetContent>
    </Sheet>
  );
}
