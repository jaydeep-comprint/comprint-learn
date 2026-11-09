import { BookOpen, Loader2, MoreHorizontal, Send, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useBlocker } from "react-router";
import { toast } from "sonner";

import { ConfirmDialog, type ConfirmRequest } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useParam } from "@/features/dashboard/api";
import { useClassContext } from "@/features/dashboard/classContext";
import { errorMessage } from "@/lib/errors";
import type { PlacementOverview, PlacementStudentRow } from "@/lib/types";

import { usePlacement, useSaveChapters, useStudentAction } from "./api";
import { PlacementResultSheet } from "./PlacementResultSheet";
import { SendPlacementDialog } from "./SendPlacementDialog";
import { countsText, plural, statusText } from "./status";

function Chapters({ data, classId }: { data: PlacementOverview; classId: string }) {
  const saved = useMemo(
    () => data.chapters.filter((c) => c.covered).map((c) => c.id),
    [data.chapters],
  );
  // The parent remounts this with a new key when the saved chapters change.
  const [ticked, setTicked] = useState<string[]>(saved);
  const save = useSaveChapters(classId);
  const dirty = ticked.length !== saved.length || ticked.some((id) => !saved.includes(id));

  // Only leaving the tab counts: opening a result sheet (`?placement=`) keeps the edits.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
  );
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const { range } = data;
  return (
    <section aria-labelledby="covered-title" className="space-y-3 rounded-xl border p-4">
      <div>
        <h2 id="covered-title" className="font-semibold">
          Covered chapters
        </h2>
        <p className="text-sm text-muted-foreground">
          Tick what the class has already been taught. The placement check covers these chapters and
          everything they build on.
        </p>
      </div>
      <ul className="space-y-1.5">
        {data.chapters.map((ch) => (
          <li key={ch.id}>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={ticked.includes(ch.id)}
                disabled={data.archived}
                onCheckedChange={(v) =>
                  setTicked((prev) =>
                    v === true ? [...prev, ch.id] : prev.filter((x) => x !== ch.id),
                  )
                }
                aria-label={ch.title}
              />
              {ch.title}
              {ch.grade !== null && (
                <span className="text-xs text-muted-foreground">Class {ch.grade}</span>
              )}
            </label>
          </li>
        ))}
      </ul>
      <p className="text-sm" aria-live="polite">
        {saved.length === 0
          ? "No chapters ticked yet."
          : `${plural(range.concepts, "concept")} will be checked (${range.prereqs} of them ` +
            "prerequisites from earlier chapters or other courses)."}
      </p>
      {!data.archived && (
        <div className="flex items-center gap-3">
          <Button
            disabled={!dirty || save.isPending}
            onClick={() =>
              save.mutate(ticked, {
                onSuccess: () => toast.success("Covered chapters saved"),
                onError: (err) => toast.error(errorMessage(err)),
              })
            }
          >
            {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
            Save
          </Button>
          {dirty && <span className="text-sm text-muted-foreground">Unsaved changes</span>}
        </div>
      )}

      <AlertDialog open={blocker.state === "blocked"}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave without saving?</AlertDialogTitle>
            <AlertDialogDescription>
              Your changes to the covered chapters will be lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>Stay</AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.proceed?.()}>Leave</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function StatusTable({
  rows,
  archived,
  onOpen,
  onAction,
}: {
  rows: PlacementStudentRow[];
  archived: boolean;
  onOpen: (sid: string) => void;
  onAction: (row: PlacementStudentRow, action: "resend" | "cancel") => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Student</TableHead>
          <TableHead>Placement check</TableHead>
          <TableHead>Last result</TableHead>
          <TableHead className="w-10">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          const open = row.status === "sent" || row.status === "active";
          const closed = row.status === "finished" || row.status === "cancelled";
          return (
            <TableRow key={row.student_id}>
              <TableCell className="font-medium">
                {row.result_at ? (
                  <button
                    className="text-left hover:underline"
                    onClick={() => onOpen(row.student_id)}
                  >
                    {row.display_name}
                  </button>
                ) : (
                  row.display_name
                )}
              </TableCell>
              <TableCell>
                <Badge variant={row.status === "finished" ? "secondary" : "outline"}>
                  {statusText(row)}
                </Badge>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {countsText(row) ?? "—"}
              </TableCell>
              <TableCell>
                {(open || closed) && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Actions for ${row.display_name}`}
                      >
                        <MoreHorizontal aria-hidden />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {open && (
                        <DropdownMenuItem
                          variant="destructive"
                          disabled={archived}
                          onSelect={() => onAction(row, "cancel")}
                        >
                          Cancel
                        </DropdownMenuItem>
                      )}
                      {closed && (
                        <DropdownMenuItem
                          disabled={archived}
                          onSelect={() => onAction(row, "resend")}
                        >
                          Re-send
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** Spec 012 Placement tab: covered chapters, Send, and each student's placement status. */
export function PlacementTab() {
  const { cls } = useClassContext();
  const query = usePlacement(cls.id);
  const action = useStudentAction(cls.id);
  const [sending, setSending] = useState(false);
  const [open, setOpen] = useParam("placement");
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  if (query.isPending) return <Skeleton className="h-48" />;
  if (query.isError) {
    return (
      <div role="alert" className="text-sm">
        Couldn&apos;t load placement.{" "}
        <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  const data = query.data;
  if (!data.course) {
    return <EmptyState icon={BookOpen} title="This class has no course yet" />;
  }
  const ticked = data.chapters.some((c) => c.covered);
  const onAction = (row: PlacementStudentRow, kind: "resend" | "cancel") =>
    setConfirm({
      title:
        kind === "cancel"
          ? `Cancel ${row.display_name}'s placement check?`
          : `Re-send the placement check to ${row.display_name}?`,
      description:
        kind === "cancel"
          ? "Nothing from it will be applied. They can be sent a new one later."
          : "They take a new check. What their last one placed stays; the new one applies on top.",
      confirmLabel: kind === "cancel" ? "Cancel check" : "Re-send",
      destructive: kind === "cancel",
      onConfirm: () =>
        action.mutate(
          { sid: row.student_id, action: kind },
          {
            onSuccess: () =>
              toast.success(kind === "cancel" ? "Placement check cancelled" : "Sent"),
            onError: (err) => toast.error(errorMessage(err)),
          },
        ),
    });

  return (
    <div className="space-y-4">
      <Chapters
        key={data.chapters.map((c) => `${c.id}:${c.covered}`).join()}
        data={data}
        classId={cls.id}
      />

      <section aria-labelledby="placement-students" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="placement-students" className="font-semibold">
            Students
          </h2>
          <div className="flex items-center gap-3">
            {!ticked && !data.archived && (
              <span className="text-sm text-muted-foreground">
                Tick and save a covered chapter to send a check.
              </span>
            )}
            <Button
              onClick={() => setSending(true)}
              disabled={data.archived || !ticked || data.students.length === 0}
            >
              <Send aria-hidden />
              Send placement check
            </Button>
          </div>
        </div>
        {data.students.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No students yet"
            description="Add students to the class first."
            action={
              <Button asChild variant="outline">
                <Link to={`/classes/${cls.id}/students`}>Go to the roster</Link>
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <StatusTable
              rows={data.students}
              archived={data.archived}
              onOpen={setOpen}
              onAction={onAction}
            />
          </div>
        )}
      </section>

      <SendPlacementDialog classId={cls.id} open={sending} onClose={() => setSending(false)} />
      <PlacementResultSheet classId={cls.id} studentId={open} onClose={() => setOpen(null)} />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}
