import { Link } from "react-router";

import { Badge } from "@/components/ui/badge";
import type { AtRiskRow } from "@/lib/types";

import { Empty } from "./DashCard";

/** At-risk students with each firing rule as a chip (spec 010). */
export function AtRiskList({ classId, rows }: { classId: string; rows: AtRiskRow[] }) {
  if (rows.length === 0) return <Empty>No one is at risk this week. 🎉</Empty>;
  return (
    <ul className="divide-y">
      {rows.map((r) => (
        <li key={r.student_id} className="flex flex-wrap items-center gap-2 py-2">
          <Link
            to={`/classes/${classId}/students/${r.student_id}`}
            className="font-medium hover:underline"
          >
            {r.display_name}
          </Link>
          {r.reasons.map((reason) => (
            <Badge key={reason.code + reason.detail} variant="secondary" className="font-normal">
              {reason.detail}
            </Badge>
          ))}
        </li>
      ))}
    </ul>
  );
}
