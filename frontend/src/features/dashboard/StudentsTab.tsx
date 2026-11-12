import { Printer, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { ConfirmDialog, type ConfirmRequest } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AddStudentsDialog } from "@/features/classes/AddStudentsDialog";
import { useClassStudents } from "@/features/classes/api";
import { StudentRows } from "@/features/classes/StudentRows";
import { AssignmentDialog, type AssignmentDraft } from "@/features/assignments/AssignmentDialog";
import { ConsentBulkBar } from "@/features/privacy/consent";
import { useSelection } from "@/features/privacy/useSelection";

import { useHeatmap, useWindow } from "./api";
import { useClassContext } from "./classContext";
import { ConceptDetailSheet } from "./ConceptDetailSheet";
import { DashCard } from "./DashCard";
import { Heatmap } from "./Heatmap";

/** Spec 010 Students tab: the roster (with at-risk badges) and the concept heatmap. */
export function StudentsTab() {
  const { cls, courseSlug } = useClassContext();
  const students = useClassStudents(cls.id);
  const heatmap = useHeatmap(cls.id);
  const [window] = useWindow();
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [draft, setDraft] = useState<AssignmentDraft | null>(null);
  const [withoutConsent, setWithoutConsent] = useState(false);
  const selection = useSelection();
  const rows = (students.data ?? []).filter((s) => !withoutConsent || !s.tutor_consent_at);
  const missing = (students.data ?? []).filter((s) => !s.tutor_consent_at).length;
  const formsPath = `/classes/${cls.id}/consent-forms`;

  return (
    <div className="space-y-6">
      {students.isPending ? (
        <div className="space-y-2" aria-busy>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : students.isError ? (
        <p className="text-sm text-destructive">Couldn't load students.</p>
      ) : students.data.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No students yet"
          description="Paste a list of names to create accounts and print login slips."
          action={<AddStudentsDialog cls={cls} enrolledIds={new Set()} />}
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={withoutConsent ? "secondary" : "outline"}
              aria-pressed={withoutConsent}
              onClick={() => setWithoutConsent((v) => !v)}
            >
              Without consent ({missing})
            </Button>
            {selection.size === 0 && (
              <Button size="sm" variant="ghost" asChild>
                <Link to={formsPath}>
                  <Printer aria-hidden />
                  Print consent forms
                </Link>
              </Button>
            )}
          </div>
          <ConsentBulkBar
            selected={rows.filter((s) => selection.has(s.id))}
            onClear={selection.clear}
            confirm={setConfirm}
            printTo={formsPath}
          />
          <div className="overflow-x-auto">
            <StudentRows
              cls={cls}
              students={rows}
              confirm={setConfirm}
              selected={selection.ids}
              onSelect={selection.set}
            />
          </div>
        </div>
      )}
      <DashCard title="Concept heatmap" query={heatmap}>
        {(data) => (
          <Heatmap classId={cls.id} data={data} grade={cls.grade} onOpenConcept={setDetail} />
        )}
      </DashCard>
      <ConceptDetailSheet
        classId={cls.id}
        concept={detail}
        window={window}
        onClose={() => setDetail(null)}
        onAssign={(concept) => {
          setDetail(null);
          setDraft({ concepts: [concept] });
        }}
      />
      <AssignmentDialog
        classId={cls.id}
        courseSlug={courseSlug}
        draft={draft}
        onClose={() => setDraft(null)}
      />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}
