import { ArrowLeft, Printer, ShieldCheck } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router";

import { EmptyState } from "@/components/EmptyState";
import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/features/auth/useMe";
import { useClass, useClassStudents } from "@/features/classes/api";
import { ApiError } from "@/lib/api";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { useNotice } from "./api";
import { pickStudents } from "./forms";

function Line({ label }: { label: string }) {
  return (
    <div className="flex items-end gap-2">
      <span className="shrink-0 text-sm">{label}</span>
      <span className="h-6 flex-1 border-b border-foreground/60" />
    </div>
  );
}

/** Spec 014: printable consent forms, one A4 page per student (nothing on paper is entered). */
export function ConsentFormsView() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const me = useMe();
  const cls = useClass(id);
  const roster = useClassStudents(id);
  const notice = useNotice();

  if (cls.error instanceof ApiError && cls.error.status === 404) return <NotFoundPage />;
  const back = (
    <Button asChild variant="outline">
      <Link to={`/classes/${id}/students`}>
        <ArrowLeft aria-hidden />
        Back to students
      </Link>
    </Button>
  );
  if (cls.isError || roster.isError || notice.isError) {
    return (
      <div className="space-y-3">
        <p role="alert" className="text-sm text-destructive">
          Couldn't load the consent forms.
        </p>
        {back}
      </div>
    );
  }
  if (!cls.data || !roster.data || !notice.data || !me.data) {
    return (
      <div className="space-y-2" aria-busy>
        <Skeleton className="h-10" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  const students = pickStudents(roster.data, params.get("students"));
  if (students.length === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="No forms to print"
        description="Every student in this class already has consent recorded."
        action={back}
      />
    );
  }

  const n = notice.data;
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between print:hidden">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Consent forms</h1>
          <p className="text-sm text-muted-foreground">
            {students.length} {students.length === 1 ? "student" : "students"} · {cls.data.name}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => window.print()}>
            <Printer aria-hidden />
            Print
          </Button>
          {back}
        </div>
      </div>
      {students.map((s) => (
        <article
          key={s.id}
          aria-label={`Consent form for ${s.display_name}`}
          className="consent-form space-y-4 rounded-lg border p-6 print:rounded-none print:border-0 print:p-0 print:text-black"
        >
          <header className="space-y-1">
            <p className="text-sm text-muted-foreground print:text-black">
              {me.data.org.name} · {cls.data.name}
            </p>
            <h2 className="text-xl font-semibold">{n.title}</h2>
            <p>
              Student: <span className="font-medium">{s.display_name}</span>
            </p>
          </header>
          <Markdown className="text-sm">{n.body_md}</Markdown>
          <section className="space-y-4 pt-2">
            <p className="text-sm font-medium">
              I give consent for this student to use the AI tutor, as described above.
            </p>
            <Line label="Parent or guardian name" />
            <Line label="Relationship to the student" />
            <div className="grid gap-4 sm:grid-cols-2 print:grid-cols-2">
              <Line label="Signature" />
              <Line label="Date" />
            </div>
          </section>
          <footer className="pt-4 text-xs text-muted-foreground print:text-black">
            Form version {n.version}
          </footer>
        </article>
      ))}
    </div>
  );
}
