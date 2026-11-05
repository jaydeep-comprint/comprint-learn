import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { TodaysReviews } from "@/features/reviews/TodaysReviews";
import { renderAt } from "@/features/xp/testUtils";
import type { ReviewQueue } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

function queue(overrides: Partial<ReviewQueue> = {}): ReviewQueue {
  return {
    cap: 5,
    done_today: 3,
    offered: [
      {
        course: "physics-9-10",
        concept: { id: "physics-9-10/acceleration", title: "Acceleration" },
        subject: "physics",
        reason: "schedule",
        due_on: "2026-11-05",
        active: false,
      },
      {
        course: "maths-9-10",
        concept: { id: "maths-9-10/linear-equations", title: "Linear equations" },
        subject: "maths",
        reason: "quiz_miss",
        due_on: "2026-11-05",
        active: true,
      },
    ],
    more_due: 0,
    next_due_on: null,
    has_cards: true,
    ...overrides,
  };
}

function mock(response: () => Response) {
  vi.stubGlobal("fetch", vi.fn(routeFetch({ "GET /api/v1/reviews": response })));
}

describe("TodaysReviews", () => {
  it("lists the offered reviews with the quiz-miss badge", async () => {
    mock(() => jsonResponse(200, queue()));
    renderAt(<TodaysReviews />);
    const card = (await screen.findByRole("heading", { name: "Today's reviews" })).closest(
      "section",
    )!;
    expect(within(card).getByText("3 of 5 done today")).toBeInTheDocument();
    const links = within(card).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/review/physics-9-10/acceleration",
      "/review/maths-9-10/linear-equations",
    ]);
    expect(links[0]).toHaveTextContent("Acceleration · Physics");
    expect(links[0]).not.toHaveTextContent("From your quiz");
    expect(links[1]).toHaveTextContent("From your quiz");
    expect(links[1]).toHaveTextContent("Continue");
  });

  it("nothing due: says when the next one comes", async () => {
    mock(() => jsonResponse(200, queue({ done_today: 0, offered: [], next_due_on: "2026-11-12" })));
    renderAt(<TodaysReviews />);
    expect(await screen.findByText("No reviews due. Next one on 12 Nov.")).toBeInTheDocument();
  });

  it("cap reached: today's reviews are done", async () => {
    mock(() => jsonResponse(200, queue({ done_today: 5, offered: [], more_due: 2 })));
    renderAt(<TodaysReviews />);
    expect(await screen.findByText("That's today's reviews done 🎉")).toBeInTheDocument();
    expect(screen.getByText("5 of 5 done today")).toBeInTheDocument();
  });

  it("is hidden until the student has a card", async () => {
    const fetch = vi.fn(
      routeFetch({ "GET /api/v1/reviews": () => jsonResponse(200, queue({ has_cards: false })) }),
    );
    vi.stubGlobal("fetch", fetch);
    renderAt(<TodaysReviews />);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("heading", { name: "Today's reviews" })).not.toBeInTheDocument();
    expect(screen.queryByText(/reviews/)).not.toBeInTheDocument();
  });

  it("shows an error with a retry", { timeout: 10_000 }, async () => {
    mock(() => jsonResponse(500, { code: "internal", message: "boom" }));
    renderAt(<TodaysReviews />);
    // 5xx errors are retried twice (with backoff) before the error shows.
    expect(
      await screen.findByText("Couldn't load your reviews.", {}, { timeout: 6000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
