import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { StudentHome } from "@/features/learn/StudentHome";
import type { StudentCourse } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const P = "physics-9-10";
const course: StudentCourse = {
  slug: P,
  title: "Physics",
  subject: "physics",
  learned: 1,
  total: 4,
  brush_up: [
    {
      id: "r1",
      kind: "review",
      prereq: { id: `${P}/distance-and-displacement`, title: "Distance and displacement" },
      concept: { id: `${P}/speed-and-velocity`, title: "Speed and velocity" },
    },
  ],
  in_progress: [
    {
      id: `${P}/speed-and-velocity`,
      title: "Speed and velocity",
      kps_passed: 2,
      kps_total: 3,
      parts_passed: 2,
      parts_total: 3,
      reopen_at: null,
    },
  ],
  ready: [
    {
      id: "maths-9-10/lin",
      title: "Linear equations",
      kps_passed: 0,
      kps_total: 3,
      parts_passed: 0,
      parts_total: 3,
      reopen_at: null,
    },
  ],
  ready_count: 7,
  waiting: [
    {
      id: `${P}/acceleration`,
      title: "Acceleration",
      kps_passed: 1,
      kps_total: 3,
      parts_passed: 1,
      parts_total: 3,
      reopen_at: "2026-11-05T18:30:00Z",
    },
  ],
};

function renderHome(courses: StudentCourse[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(routeFetch({ "GET /api/v1/learn/courses": () => jsonResponse(200, courses) })),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <StudentHome firstName="Aarav" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StudentHome", () => {
  it("renders the four lists and no Continue button", async () => {
    renderHome([course]);
    expect(await screen.findByText("1 of 4 concepts learned")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue/ })).toBeNull();

    const brush = screen.getByRole("heading", { name: "Brush up" }).closest("section")!;
    expect(
      within(brush).getByRole("link", {
        name: "Brush up on Distance and displacement, needed for Speed and velocity",
      }),
    ).toHaveAttribute("href", "/learn/brush-up/r1");
    const inProgress = screen.getByRole("heading", { name: "In progress" }).closest("section")!;
    expect(within(inProgress).getByText("2 of 3 parts")).toBeInTheDocument();
    const ready = screen.getByRole("heading", { name: "Ready to learn" }).closest("section")!;
    expect(within(ready).getByRole("link", { name: /Linear equations/ })).toHaveAttribute(
      "href",
      `/learn/${P}/maths-9-10/lin`,
    );
    expect(within(ready).getByRole("link", { name: "See all on the map" })).toBeInTheDocument();
    const waiting = screen.getByRole("heading", { name: "Waiting" }).closest("section")!;
    expect(
      within(waiting).getByText("Retry tomorrow, or after you learn something else"),
    ).toBeInTheDocument();
  });

  it("hides empty lists and says when everything is learned", async () => {
    renderHome([
      {
        ...course,
        learned: 4,
        brush_up: [],
        in_progress: [],
        ready: [],
        ready_count: 0,
        waiting: [],
      },
    ]);
    expect(
      await screen.findByText("You've learned everything in this course."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Brush up" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Ready to learn" })).toBeNull();
  });
});
