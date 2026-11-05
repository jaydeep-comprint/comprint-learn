import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getAccessToken: async () => "token", signOut: async () => {} }));

import type { Leaderboard } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

import { LeaderboardPage } from "./LeaderboardPage";
import { renderAt } from "./testUtils";

const URL = "/api/v1/classes/c1/leaderboard";

function board(rows: Leaderboard["rows"]): Leaderboard {
  return {
    class_name: "9A Maths",
    subject: "maths",
    enabled: true,
    week_start: "2026-11-02",
    rows,
  };
}

function show(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(routeFetch({ [`GET ${URL}`]: () => jsonResponse(status, body) })));
  renderAt(<LeaderboardPage />, "/leaderboard/c1", "/leaderboard/:classId");
}

describe("LeaderboardPage", () => {
  it("ranks the class with your own row highlighted", async () => {
    show(
      200,
      board([
        { rank: 1, display_name: "Asha", week_xp: 30, is_me: false },
        { rank: 1, display_name: "Ravi", week_xp: 30, is_me: true },
        { rank: 3, display_name: "Meena", week_xp: 0, is_me: false },
      ]),
    );
    expect(await screen.findByRole("heading", { name: "9A Maths" })).toBeInTheDocument();
    expect(screen.getByText("This week (Mon–Sun)")).toBeInTheDocument();
    const me = screen.getByText("Ravi").closest("tr");
    expect(me).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("Asha").closest("tr")).not.toHaveAttribute("aria-current");
  });

  it("has an empty state", async () => {
    show(200, board([{ rank: 1, display_name: "Ravi", week_xp: 0, is_me: true }]));
    expect(await screen.findByText("No XP yet this week.")).toBeInTheDocument();
  });

  it("says when it isn't available (404)", async () => {
    show(404, { code: "not_found", message: "Not found." });
    expect(await screen.findByText("This leaderboard isn't available")).toBeInTheDocument();
  });
});
