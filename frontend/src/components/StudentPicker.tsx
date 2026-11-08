import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { ClassStudent } from "@/lib/types";

function toggle(list: string[], id: string, on: boolean): string[] {
  return on ? (list.includes(id) ? list : [...list, id]) : list.filter((x) => x !== id);
}

/** "Whole class" or "Choose students" (active students only, searchable). Shared by the
 * assignment dialog (spec 010) and the placement send dialog (spec 012). */
export function StudentPicker({
  students,
  whole,
  onWholeChange,
  chosen,
  onChosenChange,
  name = "audience",
}: {
  students: ClassStudent[];
  whole: boolean;
  onWholeChange: (whole: boolean) => void;
  chosen: string[];
  onChosenChange: (chosen: string[]) => void;
  name?: string;
}) {
  const [search, setSearch] = useState("");
  const active = students.filter((s) => s.status === "active");
  const shown = active.filter((s) =>
    s.display_name.toLowerCase().includes(search.trim().toLowerCase()),
  );
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-sm font-medium">Students</legend>
      <label className="flex items-center gap-2 text-sm">
        <input type="radio" name={name} checked={whole} onChange={() => onWholeChange(true)} />
        Whole class
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="radio" name={name} checked={!whole} onChange={() => onWholeChange(false)} />
        Choose students
      </label>
      {!whole && (
        <div className="space-y-2 rounded-md border p-3">
          <Input
            placeholder="Search students"
            aria-label="Search students"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <ul className="max-h-40 space-y-1 overflow-y-auto">
            {shown.map((s) => (
              <li key={s.id}>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={chosen.includes(s.id)}
                    onCheckedChange={(v) => onChosenChange(toggle(chosen, s.id, v === true))}
                    aria-label={s.display_name}
                  />
                  {s.display_name}
                </label>
              </li>
            ))}
            {shown.length === 0 && (
              <li className="text-sm text-muted-foreground">No students match.</li>
            )}
          </ul>
          <p className="text-xs text-muted-foreground">{chosen.length} chosen</p>
        </div>
      )}
    </fieldset>
  );
}
