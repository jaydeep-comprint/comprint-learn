import {
  Archive,
  ArchiveRestore,
  ArrowLeft,
  KeyRound,
  MoreHorizontal,
  Pencil,
  Plus,
  UserMinus,
  Users,
  X,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { ConfirmDialog, type ConfirmRequest } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
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
import { AddStudentsDialog } from "@/features/classes/AddStudentsDialog";
import {
  useClass,
  useClassStudents,
  useClassTeacher,
  useUnenroll,
  useUpdateClass,
} from "@/features/classes/api";
import { ClassFormDialog } from "@/features/classes/ClassFormDialog";
import { slipsStore } from "@/features/slips/store";
import { useResetPassword } from "@/features/students/api";
import { useTeachers } from "@/features/teachers/api";
import { ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { SUBJECT_LABELS, type ClassStudent, type SchoolClass } from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

function TeachersRow({ cls }: { cls: SchoolClass }) {
  const teachers = useTeachers();
  const change = useClassTeacher(cls.id);
  const onClass = new Set(cls.teachers.map((t) => t.id));
  const addable = (teachers.data ?? []).filter(
    (t) => t.status !== "deactivated" && !onClass.has(t.id),
  );

  const run = (userId: string, add: boolean) =>
    change.mutate({ userId, add }, { onError: (err) => toast.error(errorMessage(err)) });

  return (
    <div className="mb-6 flex flex-wrap items-center gap-2">
      <span className="text-sm text-muted-foreground">Teachers:</span>
      {cls.teachers.map((t) => (
        <Badge key={t.id} variant="secondary" className="gap-1 py-1 pr-1 text-sm font-normal">
          {t.display_name}
          <button
            type="button"
            className="rounded-sm p-0.5 hover:bg-background/60"
            aria-label={`Remove ${t.display_name}`}
            onClick={() => run(t.id, false)}
          >
            <X className="size-3" />
          </button>
        </Badge>
      ))}
      {cls.teachers.length === 0 && <span className="text-sm">None</span>}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" disabled={addable.length === 0}>
            <Plus aria-hidden />
            Add teacher
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuLabel>Add a co-teacher</DropdownMenuLabel>
          {addable.map((t) => (
            <DropdownMenuItem key={t.id} onSelect={() => run(t.id, true)}>
              {t.display_name}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function StudentRows({
  cls,
  students,
  confirm,
}: {
  cls: SchoolClass;
  students: ClassStudent[];
  confirm: (r: ConfirmRequest) => void;
}) {
  const navigate = useNavigate();
  const reset = useResetPassword();
  const unenroll = useUnenroll(cls.id);

  const resetPassword = (s: ClassStudent) =>
    confirm({
      title: `Reset ${s.display_name}'s password?`,
      description:
        "They'll get a new temporary password on a slip, and be signed out everywhere else.",
      confirmLabel: "Reset password",
      onConfirm: () =>
        reset.mutate(
          { id: s.id, displayName: s.display_name },
          {
            onSuccess: (slip) => {
              slipsStore.set({
                slips: [{ ...slip, display_name: s.display_name }],
                backTo: `/classes/${cls.id}`,
                backLabel: cls.name,
              });
              navigate(`/classes/${cls.id}/slips`);
            },
            onError: (err) => toast.error(errorMessage(err)),
          },
        ),
    });

  const remove = (s: ClassStudent) =>
    confirm({
      title: `Remove ${s.display_name} from ${cls.name}?`,
      description: "Their account and progress are kept. You can add them back any time.",
      confirmLabel: "Remove",
      destructive: true,
      onConfirm: () =>
        unenroll.mutate(s.id, {
          onSuccess: () => toast.success(`Removed ${s.display_name}`),
          onError: (err) => toast.error(errorMessage(err)),
        }),
    });

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Username</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="w-10">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {students.map((s) => (
          <TableRow key={s.id}>
            <TableCell className="max-w-48 truncate font-medium">{s.display_name}</TableCell>
            <TableCell className="font-mono text-sm">{s.username}</TableCell>
            <TableCell>
              <StatusBadge status={s.status} />
            </TableCell>
            <TableCell>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={`Actions for ${s.display_name}`}>
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => resetPassword(s)}>
                    <KeyRound aria-hidden />
                    Reset password
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    variant="destructive"
                    disabled={cls.archived}
                    onSelect={() => remove(s)}
                  >
                    <UserMinus aria-hidden />
                    Remove from class
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

export function ClassDetailPage() {
  const { id = "" } = useParams();
  const cls = useClass(id);
  const students = useClassStudents(id);
  const update = useUpdateClass(id);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);

  if (cls.error instanceof ApiError && (cls.error.status === 404 || cls.error.status === 422)) {
    return <NotFoundPage />;
  }
  if (cls.isPending) {
    return (
      <div className="mx-auto max-w-5xl space-y-4" aria-busy>
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  if (cls.isError) return <p className="text-sm text-destructive">Couldn't load this class.</p>;

  const c = cls.data;
  const toggleArchived = () =>
    update.mutate(
      { archived: !c.archived },
      {
        onSuccess: () => toast.success(c.archived ? `Unarchived ${c.name}` : `Archived ${c.name}`),
        onError: (err) => toast.error(errorMessage(err)),
      },
    );

  return (
    <div className="mx-auto max-w-5xl">
      <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
        <Link to="/classes">
          <ArrowLeft aria-hidden />
          Classes
        </Link>
      </Button>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {c.name}
            {c.archived && <Badge variant="outline">Archived</Badge>}
          </span>
        }
        description={`${SUBJECT_LABELS[c.subject]} · Class ${c.grade}`}
        actions={
          <>
            <ClassFormDialog
              title="Edit class"
              submitLabel="Save"
              initial={{ name: c.name, subject: c.subject, grade: c.grade }}
              trigger={
                <Button variant="outline">
                  <Pencil aria-hidden />
                  Edit
                </Button>
              }
              onSubmit={(values) => update.mutateAsync(values)}
            />
            <Button variant="outline" onClick={toggleArchived} disabled={update.isPending}>
              {c.archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
              {c.archived ? "Unarchive" : "Archive"}
            </Button>
            <AddStudentsDialog
              cls={c}
              enrolledIds={new Set((students.data ?? []).map((s) => s.id))}
            />
          </>
        }
      />
      {c.archived && (
        <p className="mb-4 rounded-lg border bg-muted/50 p-3 text-sm text-muted-foreground">
          This class is archived, so it's read-only. Unarchive it to add or remove students.
        </p>
      )}
      <TeachersRow cls={c} />

      {students.isPending ? (
        <div className="space-y-2" aria-busy>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : students.isError ? (
        <p className="text-sm text-destructive">Couldn't load students.</p>
      ) : students.data.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No students yet"
          description="Paste a list of names to create accounts and print login slips."
          action={<AddStudentsDialog cls={c} enrolledIds={new Set()} />}
        />
      ) : (
        <StudentRows cls={c} students={students.data} confirm={setConfirmRequest} />
      )}
      <ConfirmDialog request={confirmRequest} onClose={() => setConfirmRequest(null)} />
    </div>
  );
}
