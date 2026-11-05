import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Leaderboard } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Rank, name and this week's XP; the viewer's own row is highlighted. */
export function LeaderboardTable({ board }: { board: Leaderboard }) {
  if (board.rows.every((r) => r.week_xp === 0)) {
    return <p className="text-sm text-muted-foreground">No XP yet this week.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">Rank</TableHead>
          <TableHead>Name</TableHead>
          <TableHead className="text-right">XP</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {board.rows.map((r, i) => (
          <TableRow
            key={r.student_id ?? i}
            data-me={r.is_me || undefined}
            aria-current={r.is_me ? "true" : undefined}
            className={cn(r.is_me && "bg-primary/10 font-medium")}
          >
            <TableCell className="tabular-nums">{r.rank}</TableCell>
            <TableCell className="max-w-48 truncate">
              {r.display_name}
              {r.is_me && <span className="text-muted-foreground"> (you)</span>}
            </TableCell>
            <TableCell className="text-right tabular-nums">{r.week_xp}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
