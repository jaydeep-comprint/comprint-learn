import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { QuizBanner } from "@/features/quiz/QuizBanner";
import { renderAt } from "@/features/xp/testUtils";
import type { QuizState } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const pending: QuizState = {
  id: "qz1",
  status: "pending",
  total: 10,
  minutes: 15,
  deadline: null,
  seconds_left: null,
  answered: 0,
};

function mock(body: QuizState | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(routeFetch({ "GET /api/v1/quizzes/current": () => jsonResponse(200, body) })),
  );
}

describe("QuizBanner", () => {
  it("pending: Start quiz, and new lessons are paused", async () => {
    mock(pending);
    renderAt(<QuizBanner />);
    expect(await screen.findByRole("heading", { name: "Quiz time!" })).toBeInTheDocument();
    expect(screen.getByText("10 questions · 15 minutes · no notes")).toBeInTheDocument();
    expect(screen.getByText("New lessons are paused until you take it.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start quiz" })).toHaveAttribute("href", "/quiz/qz1");
  });

  it("active: Resume with the time left", async () => {
    mock({ ...pending, status: "active", seconds_left: 552, deadline: "2026-11-05T10:15:00Z" });
    renderAt(<QuizBanner />);
    expect(
      await screen.findByRole("link", { name: "Resume quiz · 9:12 left" }),
    ).toBeInTheDocument();
  });

  it("no quiz: nothing", async () => {
    const fetch = vi.fn(
      routeFetch({ "GET /api/v1/quizzes/current": () => jsonResponse(200, null) }),
    );
    vi.stubGlobal("fetch", fetch);
    renderAt(<QuizBanner />);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByText("Quiz time!")).not.toBeInTheDocument();
  });
});
