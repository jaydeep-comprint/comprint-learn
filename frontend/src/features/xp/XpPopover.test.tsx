import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getAccessToken: async () => "token", signOut: async () => {} }));

import { jsonResponse, routeFetch } from "@/test/render";

import { renderAt, summary } from "./testUtils";
import { XpPopover } from "./XpPopover";

describe("XpPopover", () => {
  it("lists today's goals, offers goals from the class goal up, and links leaderboards", () => {
    vi.stubGlobal("fetch", vi.fn(routeFetch({})));
    renderAt(
      <XpPopover
        summary={summary({
          goals: [{ subject: "maths", class_goal: 15, own_goal: 25, effective: 25 }],
          leaderboards: [{ class_id: "c1", class_name: "9A Maths", subject: "maths" }],
        })}
      />,
    );
    expect(screen.getByText("12 / 15 XP")).toBeInTheDocument();
    expect(screen.getByText("Teacher: 15")).toBeInTheDocument();
    const select = screen.getByLabelText("Maths");
    expect(select).toHaveValue("25");
    const values = within(select)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(values[0]).toBe("15");
    expect(values.at(-1)).toBe("60");
    expect(screen.getByRole("link", { name: "9A Maths" })).toHaveAttribute(
      "href",
      "/leaderboard/c1",
    );
  });

  it("saves on change (the class goal clears the own goal) and shows errors inline", async () => {
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "PUT /api/v1/me/goals/maths": (init) => {
            const body = JSON.parse(String(init.body)) as { goal: number | null };
            bodies.push(body);
            return body.goal === null
              ? jsonResponse(200, summary())
              : jsonResponse(422, {
                  code: "goal_below_class",
                  message: "Your teacher's goal is 20 XP; pick 20 or more.",
                });
          },
        }),
      ),
    );
    renderAt(
      <XpPopover
        summary={summary({
          goals: [{ subject: "maths", class_goal: 15, own_goal: 30, effective: 30 }],
        })}
      />,
    );
    await user.selectOptions(screen.getByLabelText("Maths"), "20");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your teacher's goal is 20 XP; pick 20 or more.",
    );
    await user.selectOptions(screen.getByLabelText("Maths"), "15");
    expect(bodies).toEqual([{ goal: 20 }, { goal: null }]);
  });

  it("has an empty state without classes", () => {
    renderAt(<XpPopover summary={summary({ today: [], goals: [] })} />);
    expect(screen.getByText("Join a class to get daily goals.")).toBeInTheDocument();
  });
});
