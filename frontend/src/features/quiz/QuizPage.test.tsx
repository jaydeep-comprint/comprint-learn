import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { QuizPage } from "@/features/quiz/QuizPage";
import { resetShownAwards } from "@/features/xp/awardToast";
import { renderAt } from "@/features/xp/testUtils";
import type { Question, QuizResult, QuizState } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const Q = "/api/v1/quizzes/qz1";

const pending: QuizState = {
  id: "qz1",
  status: "pending",
  total: 2,
  minutes: 3,
  deadline: null,
  seconds_left: null,
  answered: 0,
};
const active: QuizState = {
  ...pending,
  status: "active",
  deadline: "2026-11-05T10:03:00Z",
  seconds_left: 180,
};

function question(position: number): Question {
  return {
    session_id: "s1",
    position,
    item_id: `i${position}`,
    type: "mcq",
    prompt_md: `Question text ${position}`,
    unit: null,
    options: [
      { id: "1", text: "First" },
      { id: "2", text: "Second" },
    ],
    variables: null,
    results: [],
    preview_seed: null,
    deadline: active.deadline,
  };
}

const result: QuizResult = {
  correct: 1,
  total: 2,
  xp: { amount: 2, base_minutes: "1.5", goal_met_today: false, subjects: [] },
  items: [
    {
      position: 1,
      concept: { id: "physics-9-10/acceleration", title: "Acceleration" },
      type: "mcq",
      prompt_md: "Question text 1",
      response: "First",
      correct: true,
      display_answer: "First",
      explanation_md: null,
    },
    {
      position: 2,
      concept: { id: "maths-9-10/lin", title: "Linear equations" },
      type: "mcq",
      prompt_md: "Question text 2",
      response: null,
      correct: false,
      display_answer: "Second",
      explanation_md: "Because.",
    },
  ],
  review_concepts: [{ id: "maths-9-10/lin", title: "Linear equations" }],
};

function mock(initial: QuizState) {
  let state = initial;
  let position = 1;
  const answers: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(
      routeFetch({
        [`GET ${Q}`]: () => jsonResponse(200, state),
        [`POST ${Q}/start`]: () => {
          state = active;
          return jsonResponse(200, state);
        },
        [`GET ${Q}/question`]: () => jsonResponse(200, question(position)),
        [`POST ${Q}/answer`]: (init) => {
          answers.push(JSON.parse(String(init.body)));
          position += 1;
          const finished = position > 2;
          if (finished) state = { ...state, status: "finished", seconds_left: null };
          return jsonResponse(200, { saved: true, answered: position - 1, finished });
        },
        [`GET ${Q}/result`]: () => jsonResponse(200, result),
        "GET /api/v1/quizzes/current": () => jsonResponse(200, null),
      }),
    ),
  );
  return answers;
}

describe("QuizPage", () => {
  beforeEach(() => resetShownAwards());

  it("intro, start, saved answers with no feedback, then the result", async () => {
    const user = userEvent.setup();
    const answers = mock(pending);
    renderAt(<QuizPage />, "/quiz/qz1", "/quiz/:id");
    expect(await screen.findByRole("heading", { name: "Quiz time!" })).toBeInTheDocument();
    expect(screen.getByText("2 questions · 3 minutes · no notes")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start" }));

    expect(await screen.findByText("Question 1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("timer")).toHaveTextContent("3:00");
    await user.click(screen.getByLabelText("First"));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Question 2 of 2")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.queryByText("Correct!")).not.toBeInTheDocument();
    expect(screen.queryByText("Not quite")).not.toBeInTheDocument();
    expect(screen.queryByText(/Answer:/)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("First"));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByRole("heading", { name: "Quiz done" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "1 out of 2 correct" })).toBeInTheDocument();
    expect(answers).toHaveLength(2);
    expect(answers[0]).toMatchObject({ position: 1, response: "1", session_id: "s1" });
  });

  it("time out: goes to the result without submitting the current input", async () => {
    const answers = mock({ ...active, seconds_left: 0 });
    renderAt(<QuizPage />, "/quiz/qz1", "/quiz/:id");
    expect(await screen.findByRole("heading", { name: "Quiz done" })).toBeInTheDocument();
    expect(answers).toHaveLength(0);
  });
});
