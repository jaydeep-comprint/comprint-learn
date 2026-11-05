import { Archive, ArchiveRestore, Pencil } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useUpdateClass } from "@/features/classes/api";
import { ClassFormDialog } from "@/features/classes/ClassFormDialog";
import { MotivationCard } from "@/features/xp/MotivationCard";
import { errorMessage } from "@/lib/errors";

import { useClassContext } from "./classContext";

/** Spec 010: the class's goal and leaderboard (spec 008), plus edit and archive. */
export function SettingsTab() {
  const { cls } = useClassContext();
  const update = useUpdateClass(cls.id);
  const toggleArchived = () =>
    update.mutate(
      { archived: !cls.archived },
      {
        onSuccess: () =>
          toast.success(cls.archived ? `Unarchived ${cls.name}` : `Archived ${cls.name}`),
        onError: (err) => toast.error(errorMessage(err)),
      },
    );
  return (
    <div className="space-y-6">
      <MotivationCard cls={cls} />
      <Card>
        <CardHeader>
          <CardTitle>Class</CardTitle>
          <CardDescription>
            Rename the class or change its subject or grade. Archiving makes it read-only.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <ClassFormDialog
            title="Edit class"
            submitLabel="Save"
            initial={{ name: cls.name, subject: cls.subject, grade: cls.grade }}
            trigger={
              <Button variant="outline">
                <Pencil aria-hidden />
                Edit
              </Button>
            }
            onSubmit={(values) => update.mutateAsync(values)}
          />
          <Button variant="outline" onClick={toggleArchived} disabled={update.isPending}>
            {cls.archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
            {cls.archived ? "Unarchive" : "Archive"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
