import { ArrowLeft, BookOpen } from "lucide-react";
import { Link, NavLink, Outlet, useParams } from "react-router";

import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AddStudentsDialog } from "@/features/classes/AddStudentsDialog";
import { useClass, useClassStudents } from "@/features/classes/api";
import { TeachersRow } from "@/features/classes/TeachersRow";
import { useAllCourses } from "@/features/learn/api";
import { ApiError } from "@/lib/api";
import { SUBJECT_LABELS } from "@/lib/types";
import { cn } from "@/lib/utils";
import { NotFoundPage } from "@/pages/NotFoundPage";

import type { ClassContext } from "./classContext";

const TABS = [
  { to: "", label: "Overview", end: true },
  { to: "students", label: "Students", end: false },
  { to: "assignments", label: "Assignments", end: false },
  { to: "placement", label: "Placement", end: false },
  { to: "settings", label: "Settings", end: false },
];

/** Spec 010: the class page is a dashboard with four tabs (links, so they deep-link). */
export function ClassLayout() {
  const { id = "" } = useParams();
  const cls = useClass(id);
  const students = useClassStudents(id);
  const allCourses = useAllCourses();

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
  const courseSlug = allCourses.data?.find((course) => course.subject === c.subject)?.slug;
  const context: ClassContext = { cls: c, courseSlug };

  return (
    <div className="mx-auto max-w-6xl">
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
            {courseSlug && (
              <Button asChild variant="outline">
                <Link to={`/learn/${courseSlug}`}>
                  <BookOpen aria-hidden />
                  View course
                </Link>
              </Button>
            )}
            <AddStudentsDialog
              cls={c}
              enrolledIds={new Set((students.data ?? []).map((s) => s.id))}
            />
          </>
        }
      />
      {c.archived && (
        <p className="mb-4 rounded-lg border bg-muted/50 p-3 text-sm text-muted-foreground">
          This class is archived, so it's read-only. Unarchive it in Settings to make changes.
        </p>
      )}
      <TeachersRow cls={c} />
      <nav aria-label="Class sections" className="mb-6 flex gap-1 overflow-x-auto border-b">
        {TABS.map((t) => (
          <NavLink
            key={t.label}
            to={t.to === "" ? `/classes/${c.id}` : `/classes/${c.id}/${t.to}`}
            end={t.end}
            className={({ isActive }) =>
              cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap",
                isActive
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet context={context} />
    </div>
  );
}
