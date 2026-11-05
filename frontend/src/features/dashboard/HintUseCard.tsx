import { Link } from "react-router";

import type { HintUse } from "@/lib/types";

import { Empty } from "./DashCard";

const per10 = (v: number | null) => (v === null ? "—" : v.toFixed(1));

/** Hint use (spec 010): class hints per 10 questions and the top 3 students. */
export function HintUseBody({ classId, hints }: { classId: string; hints: HintUse }) {
  if (hints.answered === 0) return <Empty>No questions answered yet.</Empty>;
  return (
    <div className="space-y-3">
      <p>
        <span className="text-2xl font-semibold tabular-nums">{per10(hints.hints_per_10)}</span>{" "}
        <span className="text-sm text-muted-foreground">
          hints per 10 questions ({hints.hints} hints, {hints.chats} tutor messages)
        </span>
      </p>
      {hints.top.length > 0 && (
        <ul className="space-y-1 text-sm">
          {hints.top.map((s) => (
            <li key={s.student_id} className="flex justify-between gap-2">
              <Link to={`/classes/${classId}/students/${s.student_id}`} className="hover:underline">
                {s.display_name}
              </Link>
              <span className="tabular-nums text-muted-foreground">
                {per10(s.hints_per_10)} per 10
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
