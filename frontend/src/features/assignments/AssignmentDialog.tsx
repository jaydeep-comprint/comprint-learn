import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useClassStudents } from "@/features/classes/api";
import { useOutline } from "@/features/learn/api";
import { addDays, todayIst } from "@/lib/dates";
import { errorMessage } from "@/lib/errors";

import { useSaveAssignment } from "./api";

export const MAX_CONCEPTS = 10;
export const MAX_NOTE = 200;
export const MAX_DUE_DAYS = 180;

export type AssignmentDraft = {
  /** Set when editing. */
  id?: string;
  concepts: string[];
  due_date?: string;
  note?: string | null;
  /** null = the whole class. */
  student_ids?: string[] | null;
};

function toggle(list: string[], id: string, on: boolean): string[] {
  return on ? (list.includes(id) ? list : [...list, id]) : list.filter((x) => x !== id);
}

/** Create or edit an assignment (spec 010): 1-10 concepts of the class course, a due date from
 * today (IST) up to 6 months ahead, the whole class or chosen students, and an optional note. */
export function AssignmentDialog({
  classId,
  courseSlug,
  draft,
  onClose,
}: {
  classId: string;
  courseSlug: string | undefined;
  /** Open while set; the fields start from it. */
  draft: AssignmentDraft | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={draft !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        {/* Mounted only while open, so each draft starts a fresh form. */}
        {draft && (
          <AssignmentForm
            classId={classId}
            courseSlug={courseSlug}
            draft={draft}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function AssignmentForm({
  classId,
  courseSlug,
  draft,
  onClose,
}: {
  classId: string;
  courseSlug: string | undefined;
  draft: AssignmentDraft;
  onClose: () => void;
}) {
  const outline = useOutline(courseSlug ?? "", !!courseSlug);
  const students = useClassStudents(classId);
  const save = useSaveAssignment(classId);
  const today = todayIst();

  const [concepts, setConcepts] = useState<string[]>(() => draft.concepts.slice(0, MAX_CONCEPTS));
  const [due, setDue] = useState(() => draft.due_date ?? addDays(today, 7));
  const [note, setNote] = useState(draft.note ?? "");
  const [whole, setWhole] = useState(draft.student_ids == null);
  const [chosen, setChosen] = useState<string[]>(draft.student_ids ?? []);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Only the class course's own concepts (borrowed cross-course prerequisites are left out).
  const chapters = useMemo(
    () =>
      (outline.data?.chapters ?? [])
        .map((ch) => ({
          ...ch,
          concepts: ch.concepts.filter((c) => c.id.startsWith(`${courseSlug}/`)),
        }))
        .filter((ch) => ch.concepts.length > 0),
    [outline.data, courseSlug],
  );
  const active = (students.data ?? []).filter((s) => s.status === "active");
  const shown = active.filter((s) =>
    s.display_name.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const full = concepts.length >= MAX_CONCEPTS;

  function setChapter(ids: string[], on: boolean) {
    setConcepts((prev) => {
      if (!on) return prev.filter((c) => !ids.includes(c));
      const next = [...prev];
      for (const id of ids) {
        if (next.length >= MAX_CONCEPTS) break;
        if (!next.includes(id)) next.push(id);
      }
      return next;
    });
  }

  function validate(): string | null {
    if (concepts.length < 1 || concepts.length > MAX_CONCEPTS) return "Pick 1 to 10 concepts.";
    const dueChanged = draft.id === undefined || due !== draft.due_date;
    if (!due || (dueChanged && (due < today || due > addDays(today, MAX_DUE_DAYS)))) {
      return "Pick a due date from today up to 6 months ahead.";
    }
    if (note.trim().length > MAX_NOTE) return "Notes can be up to 200 characters.";
    if (!whole && chosen.length === 0) return "Choose at least one student.";
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    try {
      await save.mutateAsync({
        id: draft.id ?? null,
        body: {
          concepts,
          due_date: due,
          note: note.trim() || null,
          student_ids: whole ? null : chosen,
        },
      });
      toast.success(draft.id ? "Assignment saved" : "Assignment created");
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{draft.id ? "Edit assignment" : "New assignment"}</DialogTitle>
        <DialogDescription>
          Assigned concepts come first for students. They can still learn anything else.
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={(e) => void submit(e)} className="grid gap-5">
        <fieldset className="grid gap-2">
          <legend className="mb-1 flex w-full items-center justify-between text-sm font-medium">
            Concepts
            <span className="font-normal text-muted-foreground" aria-live="polite">
              {concepts.length} of {MAX_CONCEPTS}
            </span>
          </legend>
          {!courseSlug || outline.isError ? (
            <p className="text-sm text-destructive">Couldn't load the course.</p>
          ) : outline.isPending ? (
            <Skeleton className="h-32" />
          ) : chapters.length === 0 ? (
            <p className="text-sm text-muted-foreground">This course has no concepts yet.</p>
          ) : (
            <div className="max-h-64 space-y-3 overflow-y-auto rounded-md border p-3">
              {chapters.map((ch) => {
                const ids = ch.concepts.map((c) => c.id);
                const picked = ids.filter((i) => concepts.includes(i)).length;
                return (
                  <div key={ch.slug} className="space-y-1">
                    <label className="flex items-center gap-2 text-sm font-medium">
                      <Checkbox
                        checked={
                          picked === ids.length ? true : picked > 0 ? "indeterminate" : false
                        }
                        onCheckedChange={(v) => setChapter(ids, v === true)}
                        aria-label={`All of ${ch.title}`}
                      />
                      {ch.title}
                    </label>
                    <ul className="space-y-1 pl-6">
                      {ch.concepts.map((c) => {
                        const on = concepts.includes(c.id);
                        return (
                          <li key={c.id}>
                            <label className="flex items-center gap-2 text-sm">
                              <Checkbox
                                checked={on}
                                disabled={!on && full}
                                onCheckedChange={(v) =>
                                  setConcepts((prev) => toggle(prev, c.id, v === true))
                                }
                                aria-label={c.title}
                              />
                              {c.title}
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}
        </fieldset>

        <div className="grid gap-2">
          <Label htmlFor="assignment-due">Due date</Label>
          <Input
            id="assignment-due"
            type="date"
            value={due}
            min={today}
            max={addDays(today, MAX_DUE_DAYS)}
            onChange={(e) => setDue(e.target.value)}
            required
          />
        </div>

        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium">Students</legend>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="audience" checked={whole} onChange={() => setWhole(true)} />
            Whole class
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="audience" checked={!whole} onChange={() => setWhole(false)} />
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
                        onCheckedChange={(v) => setChosen((prev) => toggle(prev, s.id, v === true))}
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

        <div className="grid gap-2">
          <Label htmlFor="assignment-note" className="flex justify-between">
            Note for students (optional)
            <span className="font-normal text-muted-foreground">
              {note.trim().length}/{MAX_NOTE}
            </span>
          </Label>
          <Textarea
            id="assignment-note"
            value={note}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        <FormError message={error} />
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : draft.id ? "Save" : "Assign"}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
