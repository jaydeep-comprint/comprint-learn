import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getAccessToken: async () => "token", signOut: async () => {} }));

import type { SchoolClass } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

import { MotivationCard } from "./MotivationCard";
import { renderAt } from "./testUtils";

const cls: SchoolClass = {
  id: "c1",
  name: "9A Maths",
  subject: "maths",
  grade: 9,
  archived: false,
  student_count: 2,
  teachers: [],
  daily_goal: 15,
  leaderboard_enabled: false,
};

describe("MotivationCard", () => {
  it("sets the goal, switches the leaderboard on, and shows the table with an Off badge", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/classes/c1/leaderboard": () =>
            jsonResponse(200, {
              class_name: "9A Maths",
              subject: "maths",
              enabled: false,
              week_start: "2026-11-02",
              rows: [
                { rank: 1, display_name: "Ravi", week_xp: 12, is_me: false, student_id: "s1" },
              ],
            }),
          "PATCH /api/v1/classes/c1": (init) => {
            const body = JSON.parse(String(init.body)) as Partial<SchoolClass>;
            patches.push(body);
            return jsonResponse(200, { ...cls, ...body });
          },
        }),
      ),
    );
    renderAt(<MotivationCard cls={cls} />);
    expect(await screen.findByText("Ravi")).toBeInTheDocument();
    expect(screen.getByText("Off: students can't see this")).toBeInTheDocument();
    expect(
      screen.getByText("Students in this class see a weekly XP ranking. Off by default."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Daily goal")).toHaveValue("15");

    await user.selectOptions(screen.getByLabelText("Daily goal"), "20");
    await user.click(screen.getByRole("switch", { name: "Class leaderboard" }));
    expect(patches).toEqual([{ daily_goal: 20 }, { leaderboard_enabled: true }]);
  });
});
