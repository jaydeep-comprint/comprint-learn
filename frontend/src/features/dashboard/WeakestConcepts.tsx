import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ConceptStat } from "@/lib/types";

import { Empty } from "./DashCard";
import { pct } from "./format";

/** The class's weakest concepts (spec 010): fail rate, tried, stuck now, % learned, Assign. */
export function WeakestConcepts({
  rows,
  onOpen,
  onAssign,
}: {
  rows: ConceptStat[];
  onOpen: (concept: string) => void;
  onAssign: (concept: string) => void;
}) {
  if (rows.length === 0) {
    return <Empty>Not enough practice yet to rank concepts. Check back after a few lessons.</Empty>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Concept</TableHead>
          <TableHead className="text-right">Fail rate</TableHead>
          <TableHead className="text-right">Tried</TableHead>
          <TableHead className="text-right">Stuck now</TableHead>
          <TableHead className="text-right">Learned</TableHead>
          <TableHead className="w-20">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.concept}>
            <TableCell>
              <button
                type="button"
                className="text-left font-medium hover:underline"
                onClick={() => onOpen(r.concept)}
              >
                {r.title}
              </button>
              <span className="block text-xs text-muted-foreground">{r.chapter}</span>
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {r.fail_rate === null ? (
                <span className="text-xs text-muted-foreground">Not enough tries yet</span>
              ) : (
                pct(r.fail_rate)
              )}
            </TableCell>
            <TableCell className="text-right tabular-nums">{r.students_tried}</TableCell>
            <TableCell className="text-right tabular-nums">{r.stuck_now}</TableCell>
            <TableCell className="text-right tabular-nums">{r.learned_pct}%</TableCell>
            <TableCell>
              <Button variant="outline" size="sm" onClick={() => onAssign(r.concept)}>
                Assign
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
