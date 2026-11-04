import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QuestionStep } from "@/features/learn/QuestionStep";
import type { AnswerResult, Question } from "@/lib/types";

const numeric: Question = {
  session_id: "s",
  position: 2,
  item_id: "i",
  type: "numeric",
  prompt_md: "How fast?",
  unit: "m/s",
  options: null,
  variables: null,
  results: [false],
  preview_seed: null,
};

const mcq: Question = {
  ...numeric,
  type: "mcq",
  unit: null,
  options: [
    { id: "1", text: "16 km/h" },
    { id: "2", text: "18 km/h" },
  ],
};

function result(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    correct: false,
    display_answer: "8 m/s",
    explanation_md: "Distance over time.",
    misconception: null,
    note: null,
    session_status: "active",
    already_answered: false,
    results: [false, false],
    concept_learned: false,
    unlocked: [],
    remediations: [],
    ...overrides,
  };
}

function setup(props: Partial<Parameters<typeof QuestionStep>[0]> = {}) {
  const handlers = { onSubmit: vi.fn(), onNext: vi.fn(), onContinue: vi.fn() };
  render(
    <QuestionStep
      header="Practice · Speed"
      question={numeric}
      result={null}
      submitting={false}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("QuestionStep", () => {
  it("keeps Submit disabled until there is input, then submits the trimmed text", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup();
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Your answer"), " 8 ");
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledWith("8");
  });

  it("shows this session's answers as dots, the current one hollow", () => {
    setup();
    expect(screen.getAllByTestId("dot-wrong")).toHaveLength(1);
    expect(screen.getByTestId("dot-current")).toBeInTheDocument();
  });

  it("after a wrong answer: the answer, note, misconception, explanation and Next question", async () => {
    const user = userEvent.setup();
    const { onNext } = setup({
      result: result({ note: "Give 3 significant figures", misconception: { title: "Mix-up" } }),
    });
    expect(screen.getByText("Not quite")).toBeInTheDocument();
    expect(screen.getByText("Give 3 significant figures")).toBeInTheDocument();
    expect(screen.getByText("8 m/s")).toBeInTheDocument();
    expect(screen.getByText("Common mix-up: Mix-up")).toBeInTheDocument();
    expect(screen.getByText("Distance over time.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Next question" }));
    expect(onNext).toHaveBeenCalled();
  });

  it("on pass: the banner and Continue", async () => {
    const user = userEvent.setup();
    const { onContinue } = setup({
      result: result({ correct: true, session_status: "passed", results: [false, true, true] }),
    });
    expect(screen.getByText("Correct!")).toBeInTheDocument();
    expect(screen.getByText("Part passed ✓")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(onContinue).toHaveBeenCalled();
  });

  it("on fail: Continue without the pass banner", () => {
    setup({ result: result({ session_status: "failed" }) });
    expect(screen.queryByText("Part passed ✓")).toBeNull();
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("MCQ: radio cards, and the correct option's text as the answer", async () => {
    const user = userEvent.setup();
    const { onSubmit } = setup({ question: mcq });
    await user.click(screen.getByRole("radio", { name: "18 km/h" }));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).toHaveBeenCalledWith("2");
  });

  it("staff preview: no dots, Another question", () => {
    setup({ preview: true, result: result() });
    expect(screen.queryByTestId("dot-wrong")).toBeNull();
    expect(screen.getByRole("button", { name: "Another question" })).toBeInTheDocument();
  });
});
