import { AlertCircle, BookOpen } from "lucide-react";
import { Link, useNavigate } from "react-router";

import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useStudentCourses } from "@/features/learn/api";
import { lessonPath } from "@/features/learn/paths";
import { ProgressBar } from "@/features/learn/ProgressBar";
import type { StudentCourse } from "@/lib/types";

function CourseCard({ course }: { course: StudentCourse }) {
  const navigate = useNavigate();
  const coursePath = `/learn/${course.slug}`;
  const allDone = course.total > 0 && course.finished === course.total;
  return (
    // The whole card opens the course; the button inside goes straight to the next lesson.
    <div
      className="cursor-pointer space-y-4 rounded-xl border p-4 transition-colors hover:bg-muted/50 sm:p-5"
      onClick={() => navigate(coursePath)}
    >
      <h2 className="text-lg font-semibold">
        <Link to={coursePath} onClick={(e) => e.stopPropagation()} className="hover:underline">
          {course.title}
        </Link>
      </h2>
      <ProgressBar
        value={course.finished}
        total={course.total}
        label={`${course.finished} of ${course.total} concepts finished`}
      />
      <div onClick={(e) => e.stopPropagation()}>
        {course.continue ? (
          <Button asChild className="w-full sm:w-auto">
            <Link to={lessonPath(course.slug, course.continue.id)}>
              Continue: {course.continue.title}
            </Link>
          </Button>
        ) : (
          <Button asChild variant={allDone ? "default" : "outline"} className="w-full sm:w-auto">
            <Link to={coursePath}>{allDone ? "Review course" : "Open course"}</Link>
          </Button>
        )}
      </div>
    </div>
  );
}

export function StudentHome({ firstName }: { firstName: string }) {
  const courses = useStudentCourses();
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold sm:text-3xl">Hi {firstName}</h1>
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
