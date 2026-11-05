import { Flag } from "lucide-react";
import { Link } from "react-router";

import { shortDate } from "@/lib/dates";
import type { FlaggedThread } from "@/lib/types";

import { Empty } from "./DashCard";

/** Flagged tutor chats (spec 010): each opens the student page with the thread open. */
export function FlaggedChats({ classId, rows }: { classId: string; rows: FlaggedThread[] }) {
  if (rows.length === 0) return <Empty>No flagged chats.</Empty>;
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((t) => (
        <li key={t.thread_id}>
          <Link
            to={`/classes/${classId}/students/${t.student_id}?thread=${t.thread_id}`}
            className="flex items-center gap-2 rounded px-1 py-1 hover:bg-muted"
          >
            <Flag className="size-4 text-destructive" aria-hidden />
            <span className="font-medium">{t.display_name}</span>
            <span className="flex-1 truncate text-muted-foreground">{t.concept_title}</span>
            <span className="tabular-nums text-muted-foreground">{shortDate(t.created_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
