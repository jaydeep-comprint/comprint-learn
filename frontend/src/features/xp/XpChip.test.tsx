import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getAccessToken: async () => "token", signOut: async () => {} }));

import { jsonResponse, routeFetch } from "@/test/render";

import { renderAt, summary } from "./testUtils";
import { XpChip } from "./XpChip";

function mockSummary(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(routeFetch({ "GET /api/v1/me/xp": () => jsonResponse(status, body) })),
  );
}

describe("XpChip", () => {
  it("shows a skeleton while loading", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    renderAt(<XpChip />);
    expect(screen.getByTestId("xp-chip-loading")).toBeInTheDocument();
  });

  it("shows the streak and today's XP over today's goals; the flame is muted until met", async () => {
    mockSummary(
      summary({
        today: [
          { subject: "maths", xp: 12, goal: 15, met: false },
          { subject: "physics", xp: 10, goal: 15, met: false },
        ],
      }),
    );
    renderAt(<XpChip />);
    const chip = await screen.findByRole("button", { name: "Streak 4 days, 22 of 30 XP today" });
    expect(chip).toHaveTextContent("4· 22/30");
    expect(chip.querySelector("svg")).toHaveAttribute("data-met", "false");
    // Phone width: only the flame and streak (the XP part is `hidden sm:inline`).
    expect(screen.getByTestId("xp-chip-today")).toHaveClass("hidden", "sm:inline");
  });

  it("lights the flame once today is met", async () => {
    mockSummary(summary({ streak: { days: 5, today_met: true } }));
    renderAt(<XpChip />);
    const chip = await screen.findByRole("button", { name: /Streak 5 days/ });
    expect(chip.querySelector("svg")).toHaveAttribute("data-met", "true");
  });

  it("is hidden on error", async () => {
    mockSummary({ code: "forbidden", message: "no" }, 403);
    renderAt(<XpChip />);
    await waitFor(() => expect(screen.queryByTestId("xp-chip-loading")).not.toBeInTheDocument());
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("opens the popover", async () => {
    const user = userEvent.setup();
    mockSummary(summary());
    renderAt(<XpChip />);
    await user.click(await screen.findByRole("button", { name: /Streak 4 days/ }));
    expect(await screen.findByText("Streak: 4 days")).toBeInTheDocument();
    expect(screen.getByText("Meet today's goals to make it 5")).toBeInTheDocument();
    expect(screen.getByText("This week: 84 XP")).toBeInTheDocument();
  });
});
