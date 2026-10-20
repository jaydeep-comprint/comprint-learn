import { Plus, School, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useClasses, useCreateClass } from "@/features/classes/api";
import { ClassFormDialog } from "@/features/classes/ClassFormDialog";
import { SUBJECT_LABELS, type SchoolClass } from "@/lib/types";

function ClassCard({ cls }: { cls: SchoolClass }) {
  return (
    <Link
      to={`/classes/${cls.id}`}
      className="rounded-xl focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <Card className="h-full gap-3 transition-colors hover:bg-accent/50">
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="truncate">{cls.name}</CardTitle>
            {cls.archived && <Badge variant="outline">Archived</Badge>}
          </div>
          <CardDescription>
            {SUBJECT_LABELS[cls.subject]} · Class {cls.grade}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1 text-sm text-muted-foreground">
          <p className="flex items-center gap-2">
            <Users className="size-4" aria-hidden />
            {cls.student_count} {cls.student_count === 1 ? "student" : "students"}
          </p>
          <p className="truncate">
            {cls.teachers.map((t) => t.display_name).join(", ") || "No teachers"}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

export function ClassesPage() {
  const [tab, setTab] = useState<"mine" | "all">("mine");
  const [showArchived, setShowArchived] = useState(false);
  const classes = useClasses(tab === "mine", showArchived);
  const createClass = useCreateClass();

  const newClassButton = (
    <ClassFormDialog
      title="New class"
      submitLabel="Create class"
      trigger={
        <Button>
          <Plus aria-hidden />
          New class
        </Button>
      }
      onSubmit={async (values) => {
        await createClass.mutateAsync(values);
        toast.success(`Created ${values.name}`);
      }}
    />
  );

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Classes" actions={newClassButton} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs value={tab} onValueChange={(v) => setTab(v as "mine" | "all")}>
          <TabsList>
            <TabsTrigger value="mine">My classes</TabsTrigger>
            <TabsTrigger value="all">All classes</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-2">
          <Switch id="show-archived" checked={showArchived} onCheckedChange={setShowArchived} />
          <Label htmlFor="show-archived">Show archived</Label>
        </div>
      </div>

      {classes.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : classes.isError ? (
        <p className="text-sm text-destructive">Couldn't load classes.</p>
      ) : classes.data.length === 0 ? (
        <EmptyState
          icon={School}
          title={tab === "mine" ? "You don't have any classes yet" : "No classes yet"}
          description="Create a class, then add students to it."
          action={newClassButton}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {classes.data.map((cls) => (
            <ClassCard key={cls.id} cls={cls} />
          ))}
        </div>
      )}
    </div>
  );
}
