import { screen, within } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuizResultView } from "@/features/quiz/QuizResult";
import { resetShownAwards } from "@/features/xp/awardToast";
import { renderAt } from "@/features/xp/testUtils";
import type { QuizResult } from "@/lib/types";

const result: QuizResult = {
  correct: 8,
  total: 10,
  xp: {
    amount: 11,
    base_minutes: "9",
    goal_met_today: true,
    subjects: [
      { subject: "maths", amount: 6, grade: "passed" },
      { subject: "physics", amount: 5, grade: "passed" },
    ],
  },
  items: [
    {
      position: 1,
      concept: { id: "physics-9-10/acceleration", title: "Acceleration" },
      type: "numeric",
      prompt_md: "A car goes from 0 to 20 m/s in 4 s. Its acceleration?",
      response: "4 m/s^2",
      correct: false,
      display_answer: "5 m/s^2",
      explanation_md: "a = Δv / t.",
    },
    {
      position: 2,
      concept: { id: "maths-9-10/lin", title: "Linear equations" },
      type: "expression",
      prompt_md: "Solve for y.",
      response: null,
      correct: false,
      display_answer: "2 x + 1",
      explanation_md: null,
    },
  ],
  review_concepts: [
    { id: "physics-9-10/acceleration", title: "Acceleration" },
    { id: "maths-9-10/lin", title: "Linear equations" },
  ],
};

describe("QuizResultView", () => {
  beforeEach(() => resetShownAwards());

  it("shows the score, the XP split, every answer and the new reviews", async () => {
    const success = vi.spyOn(toast, "success");
    renderAt(<QuizResultView quizId="qz1" result={result} />);
    expect(await screen.findByRole("img", { name: "8 out of 10 correct" })).toBeInTheDocument();
    expect(screen.getByText("Maths +6 XP · Physics +5 XP")).toBeInTheDocument();
    expect(success).toHaveBeenCalledWith("+11 XP · Quiz", { description: "Daily goal met 🎉" });
    const list = screen.getByRole("list", { name: "Questions" });
    const items = within(list).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Question 1 · Acceleration");
    expect(items[0]).toHaveTextContent("Your answer:4 m/s^2");
    expect(items[0]).toHaveTextContent("Answer:5 m/s^2");
    expect(items[1]).toHaveTextContent("Not answered");
    expect(
      screen.getByRole("heading", { name: "Added to your reviews" }).parentElement,
    ).toHaveTextContent("Acceleration, Linear equations");
    expect(screen.getByRole("link", { name: "Back to learning" })).toHaveAttribute("href", "/");
  });
});
