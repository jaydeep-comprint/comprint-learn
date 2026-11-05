import { ArrowLeft } from "lucide-react";
import { lazy, Suspense, useState } from "react";
import { Link, useParams } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ASSIGNMENT_STATUS } from "@/features/assignments/status";
import type { MapMode } from "@/features/graph/ConceptNode";
import { ApiError } from "@/lib/api";
import { dayDate, shortDate } from "@/lib/dates";
import type { OutlineConcept, TeacherOutlineConcept } from "@/lib/types";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { ActivityList } from "./ActivityList";
import { useStudentDetail, useStudentOutline } from "./api";
import { useClassContext } from "./classContext";
import { pct } from "./format";
import { BAND_LABELS, STATE_LABELS } from "./heat";
import { TutorThreads } from "./TutorThreads";

const CourseMap = lazy(() => import("@/features/graph/CourseMap"));

const KP_STATUS = {
  not_started: "Not started",
  in_progress: "In progress",
  passed: "Passed",
  failed: "Failed",
};

function minutes(seconds: number): string {
  return `${Math.round(seconds / 60)} min`;
}

function Details(concept: OutlineConcept) {
  const c = concept as TeacherOutlineConcept;
  return (
    <div className="space-y-3 text-sm">
      <p>
        {STATE_LABELS[c.state]}
        {c.state === "learned" && c.memory && `, ${BAND_LABELS[c.memory.band]}`}
      </p>
      {c.memory?.next_due && (
        <p className="text-muted-foreground">Next review {shortDate(c.memory.next_due)}</p>
      )}
      {c.kps.length > 0 && (
        <ul className="space-y-1">
          {c.kps.map((kp) => (
            <li key={kp.title} className="flex justify-between gap-2">
              <span>{kp.title}</span>
              <span className="text-muted-foreground">
                {KP_STATUS[kp.status]}
                {kp.fail_count > 0 && ` · ${kp.fail_count} fails`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Spec 010: one student, as their teacher sees them (read-only). */
export function StudentPage() {
  const { cls, courseSlug } = useClassContext();
  const { studentId = "" } = useParams();
  const detail = useStudentDetail(cls.id, studentId);
  const outline = useStudentOutline(cls.id, studentId);
  const [mode, setMode] = useState<MapMode>("progress");

  if (detail.error instanceof ApiError && detail.error.status === 404) return <NotFoundPage />;
  if (detail.isPending) return <Skeleton className="h-64" />;
  if (detail.isError) {
    return (
      <div role="alert" className="text-sm">
        Couldn&apos;t load this student.{" "}
        <Button variant="outline" size="sm" onClick={() => void detail.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  const d = detail.data;
  return (
    <div className="space-y-6">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to={`/classes/${cls.id}/students`}>
          <ArrowLeft aria-hidden />
          Back to class
        </Link>
      </Button>
      <header className="space-y-2">
        <h2 className="flex flex-wrap items-center gap-2 text-xl font-semibold">
          {d.display_name}
          {d.status === "deactivated" && <Badge variant="outline">Deactivated</Badge>}
        </h2>
        <div className="flex flex-wrap gap-2">
          {d.at_risk.length === 0 ? (
            <Badge variant="secondary">On track</Badge>
          ) : (
            d.at_risk.map((r) => (
              <Badge key={r.code + r.detail} variant="destructive" className="font-normal">
                {r.detail}
              </Badge>
            ))
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          {d.week_xp} XP this week · {d.streak_days}-day streak · {d.reviews_due} reviews due · Last
          quiz{" "}
          {d.last_quiz ? `${d.last_quiz.score_pct}% (${shortDate(d.last_quiz.finished_on)})` : "—"}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Last 7 days</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <p className="text-muted-foreground">Active time</p>
            <p className="font-medium">
              {minutes(d.stats.learn_seconds + d.stats.practice_seconds)} (practice{" "}
              {minutes(d.stats.practice_seconds)})
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">KP fail rate</p>
            <p className="font-medium">{pct(d.stats.kp_fail_rate)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Hints per 10 questions</p>
            <p className="font-medium">
              {d.stats.hints_per_10 === null ? "—" : d.stats.hints_per_10.toFixed(1)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Concepts learned</p>
            <p className="font-medium">
              {d.stats.learned} of {d.stats.total}
            </p>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-medium">Knowledge graph</h3>
          <div role="group" aria-label="Map view" className="inline-flex rounded-md border p-0.5">
            {(["progress", "memory"] as MapMode[]).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                onClick={() => setMode(m)}
                className={
                  mode === m
                    ? "rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
                    : "rounded px-3 py-1 text-sm hover:bg-muted"
                }
              >
                {m === "progress" ? "Progress" : "Memory"}
              </button>
            ))}
          </div>
        </div>
        {outline.isPending ? (
          <Skeleton className="h-[70vh] min-h-96 w-full" />
        ) : outline.isError || !courseSlug || !outline.data.course ? (
          <p className="text-sm text-muted-foreground">No course map for this class.</p>
        ) : (
          <Suspense fallback={<Skeleton className="h-[70vh] min-h-96 w-full" />}>
            <CourseMap
              course={courseSlug}
              outline={{ ...outline.data, course: outline.data.course }}
              mode={mode}
              details={Details}
              onShowList={() => undefined}
            />
          </Suspense>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="font-medium">Assignments</h3>
        {d.assignments.length === 0 ? (
          <p className="text-sm text-muted-foreground">No assignments.</p>
        ) : (
          <ul className="divide-y text-sm">
            {d.assignments.map((a) => (
              <li key={a.id} className="flex flex-wrap justify-between gap-2 py-2">
                <span className="font-medium">{a.title}</span>
                <span className="text-muted-foreground">
                  {ASSIGNMENT_STATUS[a.status]} · {a.learned} of {a.total} · due{" "}
                  {dayDate(a.due_date)}
                  {a.next && ` · next: ${a.next.title}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="font-medium">Recent activity</h3>
        <ActivityList classId={cls.id} studentId={studentId} />
      </section>

      <section className="space-y-2">
        <h3 className="font-medium">Tutor chats</h3>
        <TutorThreads classId={cls.id} studentId={studentId} />
      </section>
    </div>
  );
}
