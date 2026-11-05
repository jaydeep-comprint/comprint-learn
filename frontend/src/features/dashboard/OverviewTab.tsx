import { Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AddStudentsDialog } from "@/features/classes/AddStudentsDialog";
import { AssignmentDialog, type AssignmentDraft } from "@/features/assignments/AssignmentDialog";
import { dayDate } from "@/lib/dates";

import { SummaryCard } from "@/features/teacher-ai/SummaryCard";

import { useConceptStats, useMisconceptions, useOverview, useParam, useWindow } from "./api";
import { AtRiskList } from "./AtRiskList";
import { useClassContext } from "./classContext";
import { ConceptDetailSheet } from "./ConceptDetailSheet";
import { DashCard, Empty } from "./DashCard";
import { part } from "./format";
import { FlaggedChats } from "./FlaggedChats";
import { HintUseBody } from "./HintUseCard";
import { MisconceptionList } from "./MisconceptionList";
import { PracticeShare } from "./PracticeShare";
import { WeakestConcepts } from "./WeakestConcepts";
import { WindowPicker } from "./WindowPicker";

/** Spec 010 Overview: what the class needs this week, in the order a teacher acts on it. */
export function OverviewTab() {
  const { cls, courseSlug } = useClassContext();
  const [window, setWindow] = useWindow();
  const overview = useOverview(cls.id, window);
  const [allConcepts, setAllConcepts] = useState(false);
  const [allMisconceptions, setAllMisconceptions] = useState(false);
  // Summary citations link here with `?concept=` / `?misconception=` (spec 011).
  const [detail, setDetail] = useParam("concept");
  const [openMisconception, setOpenMisconception] = useParam("misconception");
  const outsideTop =
    openMisconception !== null &&
    overview.data !== undefined &&
    !overview.data.misconceptions.some((m) => m.id === openMisconception);
  const showAllMisconceptions = allMisconceptions || outsideTop;
  const concepts = useConceptStats(cls.id, window, allConcepts);
  const misconceptions = useMisconceptions(cls.id, window, showAllMisconceptions);
  const [draft, setDraft] = useState<AssignmentDraft | null>(null);
  const assign = (concept: string) => {
    setDetail(null);
    setDraft({ concepts: [concept] });
  };

  if (overview.data && overview.data.students_in_scope === 0) {
    return (
      <EmptyState
        icon={Users}
        title="Add students to see how your class is doing."
        action={<AddStudentsDialog cls={cls} enrolledIds={new Set()} />}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <WindowPicker value={window} onChange={setWindow} />
      </div>
      <SummaryCard
        key={window}
        classId={cls.id}
        window={window}
        classCourse={courseSlug}
        onAssign={(d) => {
          setDetail(null);
          setDraft(d);
        }}
      />
      <DashCard
        title="Weakest concepts"
        description="Highest KP fail rate (at least 3 students tried)."
        query={allConcepts ? concepts : part(overview, (o) => o.weakest)}
        action={
          <Button variant="ghost" size="sm" onClick={() => setAllConcepts((v) => !v)}>
            {allConcepts ? "Show top 5" : "Show all"}
          </Button>
        }
      >
        {(data) => <WeakestConcepts rows={data} onOpen={setDetail} onAssign={assign} />}
      </DashCard>
      <DashCard title="At-risk students" description="Over the last 7 days." query={overview}>
        {(data) => <AtRiskList classId={cls.id} rows={data.at_risk} />}
      </DashCard>
      <DashCard
        title="Misconceptions"
        query={showAllMisconceptions ? misconceptions : part(overview, (o) => o.misconceptions)}
        action={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setOpenMisconception(null);
              setAllMisconceptions(!showAllMisconceptions);
            }}
          >
            {showAllMisconceptions ? "Show top 5" : "Show all"}
          </Button>
        }
      >
        {(data) => (
          <MisconceptionList
            key={openMisconception ?? ""}
            rows={data}
            onAssign={assign}
            openId={openMisconception}
          />
        )}
      </DashCard>
      <div className="grid gap-4 md:grid-cols-2">
        <DashCard id="hints" title="Hint use" query={overview}>
          {(data) => <HintUseBody classId={cls.id} hints={data.hints} />}
        </DashCard>
        <DashCard title="Flagged chats" query={overview}>
          {(data) => <FlaggedChats classId={cls.id} rows={data.flagged} />}
        </DashCard>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <DashCard id="time" title="Time in practice" query={overview}>
          {(data) => (
            <PracticeShare
              learnSeconds={data.practice_share.learn_seconds}
              practiceSeconds={data.practice_share.practice_seconds}
            />
          )}
        </DashCard>
        <DashCard
          title="Assignments due soon"
          query={overview}
          action={
            <Button asChild variant="ghost" size="sm">
              <Link to={`/classes/${cls.id}/assignments`}>All</Link>
            </Button>
          }
        >
          {(data) => (
            <div className="space-y-2 text-sm">
              {data.overdue_assignments > 0 && (
                <Badge variant="destructive">{data.overdue_assignments} overdue</Badge>
              )}
              {data.assignments_due.length === 0 ? (
                <Empty>No assignments due.</Empty>
              ) : (
                <ul className="space-y-1">
                  {data.assignments_due.map((a) => (
                    <li key={a.id} className="flex justify-between gap-2">
                      <span className="truncate">{a.title}</span>
                      <span className="whitespace-nowrap text-muted-foreground tabular-nums">
                        {a.counts.done}/{a.counts.total} done · {dayDate(a.due_date)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </DashCard>
      </div>
      <ConceptDetailSheet
        classId={cls.id}
        concept={detail}
        window={window}
        onClose={() => setDetail(null)}
        onAssign={assign}
      />
      <AssignmentDialog
        classId={cls.id}
        courseSlug={courseSlug}
        draft={draft}
        onClose={() => setDraft(null)}
      />
    </div>
  );
}
