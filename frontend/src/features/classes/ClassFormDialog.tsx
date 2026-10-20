import { useState, type FormEvent, type ReactNode } from "react";

import { FormError } from "@/components/FormError";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { ClassInput } from "@/features/classes/api";
import { errorMessage } from "@/lib/errors";
import { SUBJECT_LABELS, type Subject } from "@/lib/types";

/** "New class" and "Edit class": name (1-40), subject, grade. */
export function ClassFormDialog({
  trigger,
  title,
  submitLabel,
  initial,
  onSubmit,
}: {
  trigger: ReactNode;
  title: string;
  submitLabel: string;
  initial?: ClassInput;
  onSubmit: (values: ClassInput) => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(initial?.name ?? "");
  const [subject, setSubject] = useState<Subject>(initial?.subject ?? "maths");
  const [grade, setGrade] = useState<9 | 10>(initial?.grade ?? 9);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      setName(initial?.name ?? "");
      setSubject(initial?.subject ?? "maths");
      setGrade(initial?.grade ?? 9);
      setError(null);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > 40) {
      setError("Class names are 1-40 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ name: trimmed, subject, grade });
      setOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>For example "9A Maths".</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="class-name">Name</Label>
            <Input
              id="class-name"
              value={name}
              maxLength={40}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="class-subject">Subject</Label>
              <Select
                id="class-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value as Subject)}
              >
                {Object.entries(SUBJECT_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="class-grade">Grade</Label>
              <Select
                id="class-grade"
                value={grade}
                onChange={(e) => setGrade(Number(e.target.value) as 9 | 10)}
              >
                <option value={9}>Class 9</option>
                <option value={10}>Class 10</option>
              </Select>
            </div>
          </div>
          <FormError message={error} />
          <DialogFooter>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
