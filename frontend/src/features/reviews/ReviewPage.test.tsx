import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { ReviewPage } from "@/features/reviews/ReviewPage";
import { resetShownAwards } from "@/features/xp/awardToast";
import { renderAt } from "@/features/xp/testUtils";
import type { AnswerResult, Question, ReviewOutcome } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const REF = "physics-9-10/acceleration";
const BASE = `/api/v1/reviews/${REF}`;

const question: Question = {
  session_id: "s1",
  position: 3,
  item_id: "i1",
  type: "mcq",
  prompt_md: "Which is a vector?",
  unit: null,
  options: [
    { id: "1", text: "Speed" },
    { id: "2", text: "Velocity" },
  ],
  variables: null,
  results: [true, true],
  preview_seed: null,
};

function result(status: "passed" | "failed", review: ReviewOutcome): AnswerResult {
  return {
    correct: status === "passed",
    display_answer: "2",
    explanation_md: null,
    misconception: null,
    note: null,
    session_status: status,
    already_answered: false,
    results: [true, true, status === "passed"],
    concept_learned: false,
    unlocked: [],
    remediations: [],
    review,
  };
}

function mock(answer: AnswerResult | null, conflict?: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      routeFetch({
        [`GET ${BASE}/question`]: () =>
          conflict
            ? jsonResponse(409, { code: conflict, message: "no" })
            : jsonResponse(200, question),
        [`POST ${BASE}/answer`]: () => jsonResponse(200, answer),
        "GET /api/v1/reviews": () =>
          jsonResponse(200, {
            cap: 5,
            done_today: 0,
            offered: [
              {
                course: "physics-9-10",
                concept: { id: REF, title: "Acceleration" },
                subject: "physics",
                reason: "schedule",
                due_on: "2026-11-05",
                active: true,
              },
            ],
            more_due: 0,
            next_due_on: null,
            has_cards: true,
          }),
        "POST /api/v1/learn/concepts/physics-9-10/acceleration/progress": () =>
          jsonResponse(200, { seen_steps: [], last_step: "", finished_at: null }),
      }),
    ),
  );
}

async function answerAndContinue() {
  const user = userEvent.setup();
  renderAt(<ReviewPage />, `/review/${REF}`, "/review/:course/:concept");
  expect(await screen.findByRole("heading", { name: "Review: Acceleration" })).toBeInTheDocument();
  expect(await screen.findByText("Question 3 of 3–5")).toBeInTheDocument();
  await user.click(screen.getByLabelText("Velocity"));
  await user.click(screen.getByRole("button", { name: "Submit" }));
  await user.click(await screen.findByRole("button", { name: "Continue" }));
}

describe("ReviewPage end screens", () => {
  beforeEach(() => resetShownAwards());

  it("passed: see you again on the next due date", async () => {
    mock(result("passed", { rating: "good", next_due: "2026-11-12", relearn: false }));
    await answerAndContinue();
    expect(await screen.findByText("Nice, see you again on 12 Nov")).toBeInTheDocument();
  });

  it("first fail: again tomorrow", async () => {
    mock(result("failed", { rating: "again", next_due: "2026-11-06", relearn: false }));
    await answerAndContinue();
    expect(await screen.findByText("We'll review this again tomorrow")).toBeInTheDocument();
  });

  it("second fail: relearn, with a link to the lesson", async () => {
    mock(result("failed", { rating: "again", next_due: null, relearn: true }));
    await answerAndContinue();
    expect(await screen.findByText("Let's relearn Acceleration")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the lesson" })).toHaveAttribute(
      "href",
      `/learn/physics-9-10/${REF}`,
    );
  });

  it("over the cap: a friendly panel with a link home", async () => {
    mock(null, "review_cap");
    renderAt(<ReviewPage />, `/review/${REF}`, "/review/:course/:concept");
    expect(
      await screen.findByText("That's today's reviews done. More tomorrow."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back home" })).toHaveAttribute("href", "/");
  });
});
