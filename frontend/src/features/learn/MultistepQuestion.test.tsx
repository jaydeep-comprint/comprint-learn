import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QuestionStep } from "@/features/learn/QuestionStep";
import type { AnswerResult, Question, StepResult } from "@/lib/types";

const problem: Question = {
  session_id: "s",
  position: 1,
  item_id: "ms",
  type: "multistep",
  prompt_md: "A car drives 100 km out at 80 km/h and back at 50 km/h.",
  unit: null,
  options: null,
  variables: null,
  steps: [
    { prompt_md: "Time out?", type: "numeric", unit: "h", options: null, variables: null },
    { prompt_md: "Time back?", type: "numeric", unit: "h", options: null, variables: null },
    {
      prompt_md: "Which is faster?",
      type: "mcq",
      unit: null,
      options: [
        { id: "1", text: "Out" },
        { id: "2", text: "Back" },
      ],
      variables: null,
    },
  ],
  step: 0,
  step_results: [],
  results: [],
  preview_seed: null,
};

function step(correct: boolean, display: string): StepResult {
  return { correct, display_answer: display, note: null, misconception: null };
}

function result(steps: StepResult[], overrides: Partial<AnswerResult> = {}): AnswerResult {
  const last = steps[steps.length - 1];
  return {
    correct: last?.correct ?? false,
    display_answer: last?.display_answer ?? "",
    explanation_md: null,
    misconception: null,
    note: null,
    session_status: "active",
    already_answered: false,
    results: [],
    concept_learned: false,
    unlocked: [],
    remediations: [],
    step: steps.length - 1,
    step_results: steps,
    item_done: false,
    item_correct: null,
    ...overrides,
  };
}

function renderStep(question: Question, r: AnswerResult | null, onSubmit = vi.fn()) {
  const handlers = { onSubmit, onNext: vi.fn(), onContinue: vi.fn() };
  const view = render(
    <QuestionStep
      header="Practice"
      question={question}
      result={r}
      submitting={false}
      {...handlers}
    />,
  );
  return {
    ...handlers,
    rerender: (next: AnswerResult) =>
      view.rerender(
        <QuestionStep
          header="Practice"
          question={question}
          result={next}
          submitting={false}
          {...handlers}
        />,
      ),
  };
}

describe("MultistepQuestion", () => {
  it("shows one step at a time and sends the step with a unit", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderStep(problem, null);
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Time out?")).toBeInTheDocument();
    expect(screen.queryByText("Time back?")).not.toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Submit" });
    await user.type(screen.getByLabelText("Your answer"), "1.25");
    expect(submit).toBeDisabled(); // the unit box is required
    await user.type(screen.getByRole("textbox", { name: "Unit" }), "h");
    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledWith({ response: "1.25", unit: "h", step: 0 });
  });

  it("carries results forward and moves to the next step", () => {
    renderStep(problem, result([step(true, "1.25 h"), step(false, "2.00 h")]));
    const done = screen.getByTestId("steps-done");
    expect(done).toHaveTextContent("Step 1");
    expect(done).toHaveTextContent("1.25 h");
    expect(done).toHaveTextContent("Answer:");
    expect(done).toHaveTextContent("2.00 h");
    expect(screen.getByText("Step 3 of 3")).toBeInTheDocument();
    expect(screen.getByText("Which is faster?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Next|Continue/ })).not.toBeInTheDocument();
  });

  it("resumes at the step the server says, with earlier results", () => {
    renderStep({ ...problem, step: 1, step_results: [step(true, "1.25 h")] }, null);
    expect(screen.getByText("Step 2 of 3")).toBeInTheDocument();
    expect(screen.getByTestId("steps-done")).toHaveTextContent("1.25 h");
  });

  it("summarises the problem after the last step", () => {
    renderStep(
      problem,
      result([step(true, "1.25 h"), step(false, "2.00 h"), step(true, "1")], {
        item_done: true,
        item_correct: false,
        session_status: "failed",
        explanation_md: "Time = distance / speed.",
      }),
    );
    expect(screen.getByText("Not quite: 2 of 3 steps")).toBeInTheDocument();
    expect(screen.getByText("Time = distance / speed.")).toBeInTheDocument();
    expect(screen.getByTestId("steps-done")).toHaveTextContent("Out"); // the MCQ option text
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("says Problem solved when it passed", () => {
    renderStep(
      problem,
      result([step(true, "1.25 h"), step(true, "2.00 h"), step(true, "1")], {
        item_done: true,
        item_correct: true,
        session_status: "active",
      }),
    );
    expect(screen.getByText("Problem solved ✓")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next question" })).toBeInTheDocument();
  });
});
