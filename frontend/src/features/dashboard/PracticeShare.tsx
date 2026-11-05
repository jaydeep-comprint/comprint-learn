import { Empty } from "./DashCard";

/** The PRD metric "≥ 60 % of time in practice" (spec 010). */
export function PracticeShare({
  learnSeconds,
  practiceSeconds,
}: {
  learnSeconds: number;
  practiceSeconds: number;
}) {
  const total = learnSeconds + practiceSeconds;
  if (total === 0) return <Empty>No study time yet.</Empty>;
  const practice = Math.round((100 * practiceSeconds) / total);
  return (
    <div className="space-y-2">
      <p className="text-sm">
        Practice {practice} % · Learn {100 - practice} %
      </p>
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className="bg-primary" style={{ width: `${practice}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">{Math.round(total / 60)} active minutes</p>
    </div>
  );
}
