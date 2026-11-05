import { AlertCircle, BookOpen, Clock, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useStudentCourses } from "@/features/learn/api";
import { brushUpPath, lessonPath } from "@/features/learn/paths";
import { ProgressBar } from "@/features/learn/ProgressBar";
import { StatusIcon } from "@/features/learn/StatusIcon";
import { QuizBanner } from "@/features/quiz/QuizBanner";
import { TodaysReviews } from "@/features/reviews/TodaysReviews";
import type { HomeConcept, StudentCourse } from "@/lib/types";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      <ul className="space-y-1">{children}</ul>
    </section>
  );
}

function Row({ to, children }: { to: string; children: ReactNode }) {
  return (
    <li>
      <Link
        to={to}
        className="flex min-h-11 items-center gap-3 rounded-md px-2 py-2 hover:bg-muted"
      >
        {children}
      </Link>
    </li>
  );
}

/** "N of M parts": KPs plus Practice (spec 006). */
function parts(c: HomeConcept): string {
  if (c.practice_left) return "Practice left";
  return `${c.parts_passed} of ${c.parts_total} parts`;
}

function CourseCard({ course }: { course: StudentCourse }) {
  const coursePath = `/learn/${course.slug}`;
  const allDone = course.total > 0 && course.learned === course.total;
  return (
    <div className="space-y-4 rounded-xl border p-4 sm:p-5">
      <h2 className="text-lg font-semibold">
        <Link to={coursePath} className="hover:underline">
          {course.title}
        </Link>
      </h2>
      <ProgressBar
        value={course.learned}
        total={course.total}
        label={`${course.learned} of ${course.total} concepts learned`}
      />
      {allDone && <p>You&apos;ve learned everything in this course.</p>}

      {course.brush_up.length > 0 && (
        <Section title="Brush up">
          {course.brush_up.map((r) =>
            r.kind === "review" ? (
              <Row key={r.id} to={brushUpPath(r.id)}>
                <RotateCcw className="size-5 shrink-0 text-[var(--warning)]" aria-hidden />
                <span>
                  Brush up on {r.prereq.title}, needed for {r.concept.title}
                </span>
              </Row>
            ) : (
              <Row key={r.id} to={lessonPath(course.slug, r.prereq.id)}>
                <RotateCcw className="size-5 shrink-0 text-[var(--warning)]" aria-hidden />
                <span>Relearn {r.prereq.title}</span>
              </Row>
            ),
          )}
        </Section>
      )}
      {course.in_progress.length > 0 && (
        <Section title="In progress">
          {course.in_progress.map((c) => (
            <Row key={c.id} to={lessonPath(course.slug, c.id)}>
              <StatusIcon status="in_progress" />
              <span className="flex-1">{c.title}</span>
              <span className="text-sm text-muted-foreground">{parts(c)}</span>
            </Row>
          ))}
        </Section>
      )}
      {course.ready.length > 0 && (
        <Section title="Ready to learn">
          {course.ready.map((c) => (
            <Row key={c.id} to={lessonPath(course.slug, c.id)}>
              <StatusIcon status="ready" />
              <span>{c.title}</span>
            </Row>
          ))}
          {course.ready_count > course.ready.length && (
            <li>
              <Link to={coursePath} className="inline-block px-2 py-2 text-sm underline">
                See all on the map
              </Link>
            </li>
          )}
        </Section>
      )}
      {course.waiting.length > 0 && (
        <Section title="Waiting">
          {course.waiting.map((c) => (
            <Row key={c.id} to={lessonPath(course.slug, c.id)}>
              <Clock className="size-5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="flex-1">
                {c.title}
                <span className="block text-sm text-muted-foreground">
                  Retry tomorrow, or after you learn something else
                </span>
              </span>
            </Row>
          ))}
        </Section>
      )}
      <Button asChild variant="outline" className="w-full sm:w-auto">
        <Link to={coursePath}>Open course</Link>
      </Button>
    </div>
  );
}

export function StudentHome({ firstName }: { firstName: string }) {
  const courses = useStudentCourses();
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold sm:text-3xl">Hi {firstName}</h1>
      <QuizBanner />
      <TodaysReviews />
      {courses.isPending ? (
        <div className="space-y-4" aria-busy="true">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      ) : courses.isError ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border p-8 text-center">
          <AlertCircle className="size-8 text-muted-foreground" aria-hidden />
          <p>Couldn&apos;t load your courses.</p>
          <Button variant="outline" onClick={() => courses.refetch()}>
            Try again
          </Button>
        </div>
      ) : courses.data.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="You're not in a class yet."
          description="Ask your teacher to add you."
        />
      ) : (
        <div className="space-y-4">
          {courses.data.map((c) => (
            <CourseCard key={c.slug} course={c} />
          ))}
        </div>
      )}
    </div>
  );
}
