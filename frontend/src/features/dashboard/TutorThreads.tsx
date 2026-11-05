import { Flag } from "lucide-react";
import { useSearchParams } from "react-router";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { shortDate } from "@/lib/dates";
import type { ThreadDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

import { useThread, useThreads } from "./api";
import { Empty } from "./DashCard";

const STATUS_NOTE: Record<string, string> = {
  refused: "Refused (off topic)",
  safety: "Safety reply",
  error: "The tutor didn't answer",
};

function Message({ m }: { m: ThreadDetail["messages"][number] }) {
  const student = m.role === "student";
  const text = m.purged
    ? "Removed after 180 days"
    : student && m.kind === "hint"
      ? "Asked for a hint"
      : m.text;
  return (
    <li className={cn("flex", student ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 text-sm",
          student ? "bg-primary text-primary-foreground" : "bg-muted",
          m.purged && "italic opacity-70",
        )}
      >
        <p className="whitespace-pre-wrap">{text}</p>
        {STATUS_NOTE[m.status] && (
          <p className="mt-1 text-xs opacity-80">{STATUS_NOTE[m.status]}</p>
        )}
      </div>
    </li>
  );
}

/** The student's tutor threads on the class course (read-only); `?thread=` opens one. */
export function TutorThreads({ classId, studentId }: { classId: string; studentId: string }) {
  const [params, setParams] = useSearchParams();
  const open = params.get("thread");
  const threads = useThreads(classId, studentId);
  const thread = useThread(classId, studentId, open);
  const setOpen = (id: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set("thread", id);
        else next.delete("thread");
        return next;
      },
      { replace: true },
    );

  return (
    <>
      {threads.isPending ? (
        <Skeleton className="h-24" />
      ) : threads.isError ? (
        <div role="alert" className="text-sm">
          Couldn&apos;t load tutor chats.{" "}
          <Button variant="outline" size="sm" onClick={() => void threads.refetch()}>
            Try again
          </Button>
        </div>
      ) : threads.data.length === 0 ? (
        <Empty>No tutor chats.</Empty>
      ) : (
        <ul className="divide-y text-sm">
          {threads.data.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => setOpen(t.id)}
                className="flex w-full items-center gap-3 py-2 text-left hover:bg-muted"
              >
                {t.flagged ? (
                  <Flag className="size-4 shrink-0 text-destructive" aria-label="Flagged" />
                ) : (
                  <span className="size-4 shrink-0" />
                )}
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-medium">{t.concept_title}</span>
                  {t.kp_title && <span className="text-muted-foreground"> · {t.kp_title}</span>}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {t.hints_used} hints · {t.chat_count} messages · {shortDate(t.created_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent side="right" className="w-full overflow-y-auto p-4 sm:max-w-lg">
          <SheetTitle className="pr-8">{thread.data?.concept_title ?? "Tutor chat"}</SheetTitle>
          <SheetDescription>
            Read-only. The student was told their teacher can read this.
          </SheetDescription>
          {thread.isPending ? (
            <Skeleton className="h-40" />
          ) : thread.isError || !thread.data ? (
            <p className="text-sm text-destructive">Couldn&apos;t load this chat.</p>
          ) : thread.data.messages.length === 0 ? (
            <Empty>No messages.</Empty>
          ) : (
            <ul className="space-y-2">
              {thread.data.messages.map((m, i) => (
                <Message key={i} m={m} />
              ))}
            </ul>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
