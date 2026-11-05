import {
  ChevronDown,
  ChevronRight,
  ClipboardList,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, type ConfirmRequest } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useClassContext } from "@/features/dashboard/classContext";
import { dayDate } from "@/lib/dates";
import { errorMessage } from "@/lib/errors";
import type { AssignmentSummary } from "@/lib/types";

import { useAssignments, useDeleteAssignment } from "./api";
import { AssignmentDetailSheet } from "./AssignmentDetailSheet";
import { AssignmentDialog, type AssignmentDraft } from "./AssignmentDialog";

function progress(a: AssignmentSummary): string {
  if (!a.content_available) return "Content no longer available";
  if (a.counts.total === 0) return "No students";
  const overdue = a.counts.overdue ? ` · ${a.counts.overdue} overdue` : "";
  return `${a.counts.done}/${a.counts.total} done${overdue}`;
}

function Rows({
  rows,
  archived,
  onOpen,
  onEdit,
  onDelete,
}: {
  rows: AssignmentSummary[];
  archived: boolean;
  onOpen: (id: string) => void;
  onEdit: (a: AssignmentSummary) => void;
  onDelete: (a: AssignmentSummary) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Assignment</TableHead>
          <TableHead>Due</TableHead>
          <TableHead>Students</TableHead>
          <TableHead>Progress</TableHead>
          <TableHead className="w-10">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((a) => (
          <TableRow key={a.id}>
            <TableCell>
              <button
                type="button"
                className="text-left font-medium hover:underline"
                onClick={() => onOpen(a.id)}
              >
                {a.title}
              </button>
              {a.note && (
                <span className="block max-w-64 truncate text-xs text-muted-foreground">
                  {a.note}
                </span>
              )}
            </TableCell>
            <TableCell className="whitespace-nowrap">{dayDate(a.due_date)}</TableCell>
            <TableCell className="whitespace-nowrap">
              {a.all_students ? "Whole class" : `${a.student_ids.length} students`}
            </TableCell>
            <TableCell className="whitespace-nowrap tabular-nums">{progress(a)}</TableCell>
            <TableCell>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={`Actions for ${a.title}`}>
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem disabled={archived} onSelect={() => onEdit(a)}>
                    <Pencil aria-hidden />
                    Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    disabled={archived}
                    onSelect={() => onDelete(a)}
                  >
                    <Trash2 aria-hidden />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Spec 010 Assignments tab: current assignments, a collapsed "Past" section, create/edit/delete. */
export function AssignmentsTab() {
  const { cls, courseSlug } = useClassContext();
  const list = useAssignments(cls.id);
  const remove = useDeleteAssignment(cls.id);
  const [draft, setDraft] = useState<AssignmentDraft | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [showPast, setShowPast] = useState(false);

  const edit = (a: AssignmentSummary) =>
    setDraft({
      id: a.id,
      concepts: a.concepts.map((c) => c.concept),
      due_date: a.due_date,
      note: a.note,
      student_ids: a.all_students ? null : a.student_ids,
    });
  const del = (a: AssignmentSummary) =>
    setConfirm({
      title: `Delete "${a.title}"?`,
      description: "Students will no longer see it. This can't be undone.",
      confirmLabel: "Delete",
      destructive: true,
      onConfirm: () =>
        remove.mutate(a.id, {
          onSuccess: () => toast.success("Assignment deleted"),
          onError: (err) => toast.error(errorMessage(err)),
        }),
    });

  const rows = list.data ?? [];
  const current = rows.filter((a) => a.active);
  const past = rows.filter((a) => !a.active);
  const newButton = (
    <Button onClick={() => setDraft({ concepts: [] })} disabled={cls.archived}>
      <Plus aria-hidden />
      New assignment
    </Button>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">{newButton}</div>
      {list.isPending ? (
        <Skeleton className="h-32" />
      ) : list.isError ? (
        <div role="alert" className="text-sm">
          Couldn&apos;t load assignments.{" "}
          <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
            Try again
          </Button>
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="No assignments yet."
          description="Assign a concept from Overview or here."
        />
      ) : (
        <>
          {current.length > 0 ? (
            <div className="overflow-x-auto">
              <Rows
                rows={current}
                archived={cls.archived}
                onOpen={setOpen}
                onEdit={edit}
                onDelete={del}
              />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Nothing due. Past assignments are below.
            </p>
          )}
          {past.length > 0 && (
            <section>
              <button
                type="button"
                aria-expanded={showPast}
                onClick={() => setShowPast((v) => !v)}
                className="flex items-center gap-1 text-sm font-medium"
              >
                {showPast ? (
                  <ChevronDown className="size-4" />
                ) : (
                  <ChevronRight className="size-4" />
                )}
                Past ({past.length})
              </button>
              {showPast && (
                <div className="mt-2 overflow-x-auto">
                  <Rows
                    rows={past}
                    archived={cls.archived}
                    onOpen={setOpen}
                    onEdit={edit}
                    onDelete={del}
                  />
                </div>
              )}
            </section>
          )}
        </>
      )}
      <AssignmentDialog
        classId={cls.id}
        courseSlug={courseSlug}
        draft={draft}
        onClose={() => setDraft(null)}
      />
      <AssignmentDetailSheet classId={cls.id} id={open} onClose={() => setOpen(null)} />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}
