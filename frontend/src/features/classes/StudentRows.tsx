import { KeyRound, MoreHorizontal, UserMinus } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";

import type { ConfirmRequest } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useUnenroll } from "@/features/classes/api";
import { AT_RISK_LABELS } from "@/features/dashboard/atRisk";
import { ConsentStatus } from "@/features/privacy/consent";
import { slipsStore } from "@/features/slips/store";
import { useResetPassword } from "@/features/students/api";
import { shortDate } from "@/lib/dates";
import { errorMessage } from "@/lib/errors";
import type { AtRiskCode, ClassStudent, SchoolClass } from "@/lib/types";

/** Spec 010: an "At risk" badge with the firing rules in a popover. */
function AtRiskBadge({ codes }: { codes: AtRiskCode[] }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="ml-2 align-middle">
          <Badge variant="destructive">At risk</Badge>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 text-sm">
        <ul className="list-disc space-y-1 pl-4">
          {codes.map((c) => (
            <li key={c}>{AT_RISK_LABELS[c]}</li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

export function StudentRows({
  cls,
  students,
  confirm,
  selected,
  onSelect,
}: {
  cls: SchoolClass;
  students: ClassStudent[];
  confirm: (r: ConfirmRequest) => void;
  /** Spec 014: row selection for the consent bulk bar. */
  selected: ReadonlySet<string>;
  onSelect: (ids: string[], on: boolean) => void;
}) {
  const allIds = students.map((s) => s.id);
  const picked = allIds.filter((id) => selected.has(id)).length;
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
          <TableHead className="w-8">
            <Checkbox
              aria-label="Select all students"
              checked={picked === 0 ? false : picked === allIds.length ? true : "indeterminate"}
              onCheckedChange={(v) => onSelect(allIds, v === true)}
            />
          </TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Username</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Tutor consent</TableHead>
          <TableHead className="text-right">XP this week</TableHead>
          <TableHead className="text-right">Streak</TableHead>
          <TableHead className="text-right">Reviews due</TableHead>
          <TableHead>Last quiz</TableHead>
          <TableHead className="w-10">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {students.map((s) => (
          <TableRow key={s.id} data-state={selected.has(s.id) ? "selected" : undefined}>
            <TableCell>
              <Checkbox
                aria-label={`Select ${s.display_name}`}
                checked={selected.has(s.id)}
                onCheckedChange={(v) => onSelect([s.id], v === true)}
              />
            </TableCell>
            <TableCell className="max-w-48 truncate font-medium">
              <Link to={`/classes/${cls.id}/students/${s.id}`} className="hover:underline">
                {s.display_name}
              </Link>
              {s.at_risk.length > 0 && <AtRiskBadge codes={s.at_risk} />}
            </TableCell>
            <TableCell className="font-mono text-sm">{s.username}</TableCell>
            <TableCell>
              <StatusBadge status={s.status} />
            </TableCell>
            <TableCell className="whitespace-nowrap">
              <ConsentStatus student={s} />
            </TableCell>
            <TableCell className="text-right tabular-nums">{s.week_xp}</TableCell>
            <TableCell className="text-right tabular-nums">{s.streak_days}</TableCell>
            <TableCell className="text-right tabular-nums">{s.reviews_due}</TableCell>
            <TableCell className="whitespace-nowrap tabular-nums">
              {s.last_quiz
                ? `${s.last_quiz.score_pct}% · ${shortDate(s.last_quiz.finished_on)}`
                : "—"}
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
