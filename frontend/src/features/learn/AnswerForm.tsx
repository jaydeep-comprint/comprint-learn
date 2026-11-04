import { Loader2 } from "lucide-react";
import { useId, useState } from "react";

import { Markdown } from "@/components/markdown/Markdown";
import { Button } from "@/components/ui/button";
import type { AnswerFields } from "@/features/learn/api";
import { ExpressionInput } from "@/features/learn/ExpressionInput";
import { NumericInput } from "@/features/learn/NumericInput";
import type { Option, StepType } from "@/lib/types";
import { cn } from "@/lib/utils";

/** What the form needs to know about the question (or multi-step step) it answers. */
export type AnswerPart = {
  type: StepType;
  unit: string | null;
  unitRequired: boolean;
  options: Option[] | null;
  variables: string[] | null;
};

/** After an answer: which option was right, and whether the pick was. */
export type Marked = { correct: boolean; display_answer: string } | null;

function McqOptions({
  name,
  options,
  picked,
  marked,
  disabled,
  onPick,
  labelledBy,
}: {
  name: string;
  options: Option[];
  picked: string;
  marked: Marked;
  disabled: boolean;
  onPick: (id: string) => void;
  labelledBy: string;
}) {
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} className="space-y-2">
      {options.map((o) => {
        const isChosen = picked === o.id;
        const isCorrect = marked !== null && marked.display_answer === o.id;
        const isWrongPick = marked !== null && isChosen && !marked.correct;
        return (
          <label
            key={o.id}
            className={cn(
              "flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border-2 p-3 transition-colors",
              !marked && isChosen && "border-primary bg-muted",
              !marked && !isChosen && "hover:bg-muted/50",
              isCorrect && "border-[var(--success)] bg-[var(--success)]/10",
              isWrongPick && "border-destructive bg-destructive/10",
              marked && "cursor-default",
            )}
          >
            <input
              type="radio"
              name={name}
              value={o.id}
              checked={isChosen}
              disabled={disabled}
              onChange={() => onPick(o.id)}
              className="mt-1 size-4 accent-primary"
            />
            <span className="min-w-0 flex-1">
              <Markdown>{o.text}</Markdown>
            </span>
          </label>
        );
      })}
    </div>
  );
}

/** The input for a numeric (with its unit box), expression or MCQ answer, and Submit. Remount
 * it (`key`) per question or step so it starts empty. */
export function AnswerForm({
  name,
  part,
  marked,
  submitting,
  labelledBy,
  onSubmit,
}: {
  name: string;
  part: AnswerPart;
  marked: Marked;
  submitting: boolean;
  labelledBy: string;
  onSubmit: (fields: AnswerFields) => void;
}) {
  const id = useId();
  const inputId = `${id}-input`;
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const answered = marked !== null;
  const disabled = answered || submitting;
  const ready = value.trim() !== "" && (!part.unitRequired || unit.trim() !== "");

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || disabled) return;
        const fields: AnswerFields = { response: value.trim() };
        if (part.unitRequired) fields.unit = unit.trim();
        onSubmit(fields);
      }}
    >
      {part.type === "mcq" ? (
        <McqOptions
          name={name}
          options={part.options ?? []}
          picked={value}
          marked={marked}
          disabled={disabled}
          onPick={setValue}
          labelledBy={labelledBy}
        />
      ) : (
        <div className="space-y-1">
          <label htmlFor={inputId} className="text-sm font-medium">
            Your answer
          </label>
          {part.type === "numeric" ? (
            <NumericInput
              id={inputId}
              value={value}
              unit={part.unit}
              unitRequired={part.unitRequired}
              unitValue={unit}
              disabled={disabled}
              onChange={setValue}
              onUnitChange={setUnit}
            />
          ) : (
            <ExpressionInput
              id={inputId}
              value={value}
              variables={part.variables}
              disabled={disabled}
              onChange={setValue}
            />
          )}
        </div>
      )}
      {!answered && (
        <Button type="submit" disabled={!ready || submitting} className="w-full sm:w-auto">
          {submitting && <Loader2 className="animate-spin" aria-hidden />}
          Submit
        </Button>
      )}
    </form>
  );
}
