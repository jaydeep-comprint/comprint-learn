import { GraduationCap, KeyRound, MoreHorizontal, Search, UserCheck, UserX } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";
import { useNavigate } from "react-router";
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
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMe } from "@/features/auth/useMe";
import { useClasses } from "@/features/classes/api";
import { slipsStore } from "@/features/slips/store";
import { useResetPassword, useStudents, useUpdateStudent } from "@/features/students/api";
import { errorMessage } from "@/lib/errors";
import type { Student } from "@/lib/types";

export function StudentsPage() {
  const { data: me } = useMe();
  const [q, setQ] = useState("");
  const students = useStudents(useDeferredValue(q));
  const classes = useClasses(false, true);
  const classNames = useMemo(
    () => new Map((classes.data ?? []).map((c) => [c.id, c.name])),
    [classes.data],
  );
  const reset = useResetPassword();
  const update = useUpdateStudent();
  const navigate = useNavigate();
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);

  const resetPassword = (s: Student) =>
    setConfirmRequest({
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
                backTo: "/students",
                backLabel: "Students",
              });
              navigate("/slips");
            },
            onError: (err) => toast.error(errorMessage(err)),
          },
        ),
    });

  const setStatus = (s: Student, status: "active" | "deactivated") =>
    setConfirmRequest({
      title:
        status === "deactivated"
          ? `Deactivate ${s.display_name}?`
          : `Reactivate ${s.display_name}?`,
      description:
        status === "deactivated"
          ? "They'll be signed out and can't sign in until reactivated. Their data is kept."
          : "They'll be able to sign in again with their current password.",
      confirmLabel: status === "deactivated" ? "Deactivate" : "Reactivate",
      destructive: status === "deactivated",
      onConfirm: () =>
        update.mutate({ id: s.id, status }, { onError: (err) => toast.error(errorMessage(err)) }),
    });

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Students" description="Everyone in your school." />
      <div className="relative mb-4 max-w-sm">
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

      {students.isPending ? (
        <div className="space-y-2" aria-busy>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : students.isError ? (
        <p className="text-sm text-destructive">Couldn't load students.</p>
      ) : students.data.length === 0 ? (
        <EmptyState
          icon={GraduationCap}
          title={q ? "No students match" : "No students yet"}
          description={q ? undefined : "Open a class and add students to it."}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Username</TableHead>
              <TableHead>Classes</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {students.data.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="max-w-48 truncate font-medium">{s.display_name}</TableCell>
                <TableCell className="font-mono text-sm">{s.username}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {s.class_ids.map((id) => (
                      <Badge key={id} variant="outline" className="font-normal">
                        {classNames.get(id) ?? "…"}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <StatusBadge status={s.status} />
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Actions for ${s.display_name}`}
                      >
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => resetPassword(s)}>
                        <KeyRound aria-hidden />
                        Reset password
                      </DropdownMenuItem>
                      {me?.is_admin &&
                        (s.status === "deactivated" ? (
                          <DropdownMenuItem onSelect={() => setStatus(s, "active")}>
                            <UserCheck aria-hidden />
                            Reactivate
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem
                            variant="destructive"
                            onSelect={() => setStatus(s, "deactivated")}
                          >
                            <UserX aria-hidden />
                            Deactivate
                          </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <ConfirmDialog request={confirmRequest} onClose={() => setConfirmRequest(null)} />
    </div>
  );
}
