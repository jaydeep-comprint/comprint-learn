import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import { showQuizAwardToast } from "@/features/xp/awardToast";
import { type QuizResult, type QuizResultItem, SUBJECT_LABELS } from "@/lib/types";

function ScoreRing({ correct, total }: { correct: number; total: number }) {
  const r = 52;
  const circumference = 2 * Math.PI * r;
  const share = total > 0 ? correct / total : 0;
  return (
    <svg
      viewBox="0 0 120 120"
      className="size-36"
      role="img"
      aria-label={`${correct} out of ${total} correct`}
    >
      <circle cx="60" cy="60" r={r} fill="none" strokeWidth="10" className="stroke-muted" />
      <circle
        cx="60"
        cy="60"
        r={r}
        fill="none"
        strokeWidth="10"
        strokeLinecap="round"
        stroke="var(--success)"
        strokeDasharray={`${share * circumference} ${circumference}`}
        transform="rotate(-90 60 60)"
      />
      <text
        x="60"
        y="60"
        textAnchor="middle"
        dominantBaseline="central"
        className="fill-foreground text-2xl font-semibold"
      >
        {correct} / {total}
      </text>
    </svg>
  );
}

/** The correct expression is LaTeX: render it as maths (the student's raw input is shown as
 * typed). */
function asMarkdown(item: QuizResultItem, text: string): string {
  return item.type === "expression" ? "$" + text + "$" : text;
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-1">
      <span className="font-medium">{label}</span>
      {children}
    </div>
  );
}

function ItemRow({ item, open }: { item: QuizResultItem; open: boolean }) {
  return (
    <li>
      <details open={open} className="rounded-lg border p-3">
        <summary className="flex min-h-11 cursor-pointer items-center gap-3">
          {item.correct ? (
            <CheckCircle2 className="size-5 shrink-0 text-[var(--success)]" aria-hidden />
          ) : (
            <XCircle className="size-5 shrink-0 text-destructive" aria-hidden />
          )}
          <span className="min-w-0 flex-1">
            <span className="sr-only">{item.correct ? "Correct: " : "Wrong: "}</span>
            <span className="font-medium">Question {item.position}</span>
            <span className="text-muted-foreground"> · {item.concept.title}</span>
          </span>
        </summary>
        <div className="mt-3 space-y-2 border-t pt-3">
          <Markdown>{item.prompt_md}</Markdown>
          <Line label="Your answer:">
            {item.response === null ? (
              <span className="text-muted-foreground">Not answered</span>
            ) : (
              <Markdown>
                {item.type === "expression" ? "`" + item.response + "`" : item.response}
              </Markdown>
            )}
          </Line>
          <Line label="Answer:">
            <Markdown>{asMarkdown(item, item.display_answer)}</Markdown>
          </Line>
          {item.explanation_md && <Markdown>{item.explanation_md}</Markdown>}
        </div>
      </details>
    </li>
  );
}

function isWide(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(min-width: 640px)").matches;
}

/** The end of a quiz: score, XP, every question with its answer, and the misses as reviews. */
export function QuizResultView({ quizId, result }: { quizId: string; result: QuizResult }) {
  useEffect(() => {
    if (result.xp) showQuizAwardToast(result.xp, quizId);
  }, [quizId, result.xp]);
  const open = isWide(); // collapsed by default on phones
  const split = result.xp?.subjects ?? [];
  return (
    <div className="space-y-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-2xl font-semibold">Quiz done</h1>
        <ScoreRing correct={result.correct} total={result.total} />
        {split.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {split
              .map(
                (s) =>
                  `${SUBJECT_LABELS[s.subject]} ${s.amount < 0 ? "−" : "+"}${Math.abs(s.amount)} XP`,
              )
              .join(" · ")}
          </p>
        )}
      </div>
      <ul className="space-y-2" aria-label="Questions">
        {result.items.map((item) => (
          <ItemRow key={item.position} item={item} open={open} />
        ))}
      </ul>
      {result.review_concepts.length > 0 && (
        <section className="space-y-1 rounded-lg border p-4" aria-labelledby="added-reviews">
          <h2 id="added-reviews" className="font-medium">
            Added to your reviews
          </h2>
          <p>{result.review_concepts.map((c) => c.title).join(", ")}</p>
        </section>
      )}
      <Button asChild className="w-full sm:w-auto">
        <Link to="/">Back to learning</Link>
      </Button>
    </div>
  );
}
