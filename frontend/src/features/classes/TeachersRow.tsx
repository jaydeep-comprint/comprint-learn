import { Plus, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useClassTeacher } from "@/features/classes/api";
import { useTeachers } from "@/features/teachers/api";
import { errorMessage } from "@/lib/errors";
import type { SchoolClass } from "@/lib/types";

export function TeachersRow({ cls }: { cls: SchoolClass }) {
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
