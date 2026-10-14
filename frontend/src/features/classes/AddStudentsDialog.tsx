import { Search, UserPlus } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { useNavigate } from "react-router";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useCreateStudents, useEnroll } from "@/features/classes/api";
import { MAX_NEW_STUDENTS, namesError, parseNames } from "@/features/classes/names";
import { slipsStore } from "@/features/slips/store";
import { useStudents } from "@/features/students/api";
import { errorMessage } from "@/lib/errors";
import type { SchoolClass } from "@/lib/types";

function createLabel(count: number): string {
  if (count === 0) return "Create students";
  return `Create ${count} ${count === 1 ? "student" : "students"}`;
}

export function CreateStudentsForm({ cls, onDone }: { cls: SchoolClass; onDone: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const createStudents = useCreateStudents(cls.id);
  const navigate = useNavigate();
  const names = parseNames(text);
  const problem = namesError(names);

  async function submit() {
    setError(null);
    try {
      const created = await createStudents.mutateAsync(names);
      slipsStore.set({ slips: created, backTo: `/classes/${cls.id}`, backLabel: cls.name });
      onDone();
      navigate(`/classes/${cls.id}/slips`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="grid gap-3">
      <Label htmlFor="student-names">One name per line</Label>
      <Textarea
        id="student-names"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"Aarav S.\nPriya K.\nRohan M."}
        className="min-h-48"
        aria-describedby="student-names-count"
      />
      <p
        id="student-names-count"
        className={problem ? "text-sm text-destructive" : "text-sm text-muted-foreground"}
        aria-live="polite"
      >
        {problem ??
          `${names.length} ${names.length === 1 ? "name" : "names"} · max ${MAX_NEW_STUDENTS}`}
      </p>
      <p className="text-xs text-muted-foreground">
        Use a first name and initial. No surnames, roll numbers or other details are needed.
      </p>
      <FormError message={error} />
      <DialogFooter>
        <Button
          onClick={() => void submit()}
          disabled={names.length === 0 || problem !== null || createStudents.isPending}
        >
          {createStudents.isPending ? "Creating…" : createLabel(names.length)}
        </Button>
      </DialogFooter>
    </div>
  );
}

function AddExistingForm({
  cls,
  enrolledIds,
  onDone,
}: {
  cls: SchoolClass;
  enrolledIds: Set<string>;
  onDone: () => void;
}) {
  const [q, setQ] = useState("");
  const deferredQ = useDeferredValue(q);
  const students = useStudents(deferredQ);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const enroll = useEnroll(cls.id);
  const [error, setError] = useState<string | null>(null);
  const candidates = (students.data ?? []).filter(
    (s) => s.status === "active" && !enrolledIds.has(s.id),
  );

  function toggle(id: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function submit() {
    setError(null);
    try {
      await enroll.mutateAsync([...selected]);
      toast.success(`Added ${selected.size} to ${cls.name}`);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="grid gap-3">
      <div className="relative">
        <Search
          className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          aria-label="Search students"
          placeholder="Search by name or username"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="pl-9"
        />
      </div>
      <div className="max-h-72 overflow-y-auto rounded-md border">
        {students.isPending ? (
          <div className="space-y-2 p-3">
            <Skeleton className="h-6" />
            <Skeleton className="h-6" />
          </div>
        ) : candidates.length === 0 ? (
          <p className="p-4 text-center text-sm text-muted-foreground">No students to add.</p>
        ) : (
          <ul className="divide-y">
            {candidates.map((s) => (
              <li key={s.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-accent/50">
                  <Checkbox
                    checked={selected.has(s.id)}
                    onCheckedChange={(v) => toggle(s.id, v === true)}
                  />
                  <span className="min-w-0 flex-1 truncate">{s.display_name}</span>
                  <span className="font-mono text-xs text-muted-foreground">{s.username}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>
      <FormError message={error} />
      <DialogFooter>
        <Button onClick={() => void submit()} disabled={selected.size === 0 || enroll.isPending}>
          {enroll.isPending ? "Adding…" : `Add selected (${selected.size})`}
        </Button>
      </DialogFooter>
    </div>
  );
}

export function AddStudentsDialog({
  cls,
  enrolledIds,
}: {
  cls: SchoolClass;
  enrolledIds: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)} disabled={cls.archived}>
        <UserPlus aria-hidden />
        Add students
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add students to {cls.name}</DialogTitle>
            <DialogDescription>
              Create new accounts, or add students who already have one.
            </DialogDescription>
          </DialogHeader>
          {open && (
            <Tabs defaultValue="create">
              <TabsList className="w-full">
                <TabsTrigger value="create">Create new</TabsTrigger>
                <TabsTrigger value="existing">Add existing</TabsTrigger>
              </TabsList>
              <TabsContent value="create">
                <CreateStudentsForm cls={cls} onDone={() => setOpen(false)} />
              </TabsContent>
              <TabsContent value="existing">
                <AddExistingForm
                  cls={cls}
                  enrolledIds={enrolledIds}
                  onDone={() => setOpen(false)}
                />
              </TabsContent>
            </Tabs>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
