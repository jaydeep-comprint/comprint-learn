import { useMemo, useState } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Band, HeatCell, Heatmap as HeatmapData, HeatState } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Empty } from "./DashCard";
import {
  BAND_FILL,
  BAND_GLYPH,
  BAND_LABELS,
  cellLabel,
  STATE_CLASS,
  STATE_GLYPH,
  STATE_LABELS,
} from "./heat";

function Cell({ cell, label }: { cell: HeatCell; label: string }) {
  const learned = cell.state === "learned";
  const band: Band = cell.band ?? "none";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          data-state={cell.state}
          data-band={learned ? band : undefined}
          className={cn(
            "flex size-7 items-center justify-center rounded-sm text-xs font-semibold",
            !learned && STATE_CLASS[cell.state as Exclude<HeatState, "learned">],
            learned && band === "strong" && "text-white",
          )}
          style={learned ? { background: BAND_FILL[band] } : undefined}
        >
          <span aria-hidden>
            {learned ? BAND_GLYPH[band] : STATE_GLYPH[cell.state as Exclude<HeatState, "learned">]}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto max-w-64 text-sm">{label}</PopoverContent>
    </Popover>
  );
}

function Legend() {
  const states: Exclude<HeatState, "learned">[] = ["locked", "ready", "in_progress", "stuck"];
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground" role="list">
      {states.map((s) => (
        <span key={s} role="listitem" className="flex items-center gap-1">
          <span
            className={cn(
              "flex size-4 items-center justify-center rounded-sm text-[10px]",
              STATE_CLASS[s],
            )}
            aria-hidden
          >
            {STATE_GLYPH[s]}
          </span>
          {STATE_LABELS[s]}
        </span>
      ))}
      {(["strong", "fading", "weak"] as Band[]).map((b) => (
        <span key={b} role="listitem" className="flex items-center gap-1">
          <span
            className={cn(
              "flex size-4 items-center justify-center rounded-sm text-[10px]",
              b === "strong" && "text-white",
            )}
            style={{ background: BAND_FILL[b] }}
            aria-hidden
          >
            {BAND_GLYPH[b]}
          </span>
          Learned, {BAND_LABELS[b]}
        </span>
      ))}
    </div>
  );
}

/** Students × concepts (spec 010): rows are students (sticky names), columns concepts grouped by
 * chapter, defaulting to the class's grade. */
export function Heatmap({
  classId,
  data,
  grade,
  onOpenConcept,
}: {
  classId: string;
  data: HeatmapData;
  grade: number;
  onOpenConcept: (concept: string) => void;
}) {
  const [all, setAll] = useState(false);
  const indexed = useMemo(() => {
    let i = 0;
    return data.chapters.map((ch) => ({
      ...ch,
      concepts: ch.concepts.map((c) => ({ ...c, index: i++ })),
    }));
  }, [data]);
  const hasGrade = indexed.some((ch) => ch.grade === grade);
  const chapters = all || !hasGrade ? indexed : indexed.filter((ch) => ch.grade === grade);
  const columns = chapters.flatMap((ch) => ch.concepts);

  if (data.students.length === 0) return <Empty>No students yet.</Empty>;
  if (columns.length === 0) return <Empty>This class's course has no concepts yet.</Empty>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Legend />
        {hasGrade && indexed.length > chapters.length && !all && (
          <Button variant="outline" size="sm" onClick={() => setAll(true)}>
            All chapters
          </Button>
        )}
        {all && hasGrade && (
          <Button variant="outline" size="sm" onClick={() => setAll(false)}>
            Class {grade} chapters
          </Button>
        )}
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-background" />
              {chapters.map((ch) => (
                <th
                  key={ch.title}
                  colSpan={ch.concepts.length}
                  scope="colgroup"
                  className="border-b px-2 py-1 text-left text-xs font-medium text-muted-foreground"
                >
                  {ch.title}
                </th>
              ))}
            </tr>
            <tr>
              <th
                scope="col"
                className="sticky left-0 z-10 bg-background px-2 py-1 text-left font-medium"
              >
                Student
              </th>
              {columns.map((c) => (
                <th key={c.concept} scope="col" className="h-28 px-0.5 align-bottom font-normal">
                  <button
                    type="button"
                    onClick={() => onOpenConcept(c.concept)}
                    className="flex h-full w-7 flex-col items-center justify-end gap-1 hover:underline"
                    title={c.title}
                  >
                    <span className="line-clamp-1 [writing-mode:vertical-rl] rotate-180 text-xs">
                      {c.title}
                    </span>
                    <span className="text-[10px] text-muted-foreground tabular-nums">
                      {c.learned_pct}%
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.students.map((s) => (
              <tr key={s.student_id}>
                <th
                  scope="row"
                  className="sticky left-0 z-10 max-w-40 truncate bg-background px-2 py-0.5 text-left font-medium"
                >
                  <Link
                    to={`/classes/${classId}/students/${s.student_id}`}
                    className="hover:underline"
                  >
                    {s.display_name}
                  </Link>
                </th>
                {columns.map((c) => {
                  const cell = s.cells[c.index];
                  if (!cell) return <td key={c.concept} />;
                  return (
                    <td key={c.concept} className="px-0.5 py-0.5">
                      <Cell
                        cell={cell}
                        label={`${s.display_name} · ${c.title} · ${cellLabel(cell)}`}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
