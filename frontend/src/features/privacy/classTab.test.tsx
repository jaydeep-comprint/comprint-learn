import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import type { ClassContext } from "@/features/dashboard/classContext";
import { StudentsTab } from "@/features/dashboard/StudentsTab";
import type { ClassStudent, SchoolClass } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const cls: SchoolClass = {
  id: "c1",
  name: "9A Maths",
  subject: "maths",
  grade: 9,
  archived: false,
  student_count: 3,
  teachers: [],
  daily_goal: 15,
  leaderboard_enabled: false,
};

function row(id: string, name: string, extra: Partial<ClassStudent> = {}): ClassStudent {
  return {
    id,
    display_name: name,
    username: name.toLowerCase(),
    status: "active",
    week_xp: 0,
    streak_days: 0,
    reviews_due: 0,
    last_quiz: null,
    at_risk: [],
    tutor_consent_at: null,
    tutor_consent_form: null,
    erase_due_at: null,
    ...extra,
  };
}

function renderTab(students: ClassStudent[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      routeFetch({
        "GET /api/v1/classes/c1/students": () => jsonResponse(200, students),
        "GET /api/v1/classes/c1/heatmap": () => jsonResponse(200, { chapters: [], students: [] }),
      }),
    ),
  );
  const context: ClassContext = { cls, courseSlug: "maths-9-10" };
  const router = createMemoryRouter(
    [
      {
        path: "/classes/:id",
        element: <Outlet context={context} />,
        children: [{ path: "students", element: <StudentsTab /> }],
      },
      { path: "/classes/:id/consent-forms", element: <p>Forms</p> },
    ],
    { initialEntries: ["/classes/c1/students"] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("class Students tab consent (spec 014)", () => {
  it("filters to students without consent and prints the selected ones", async () => {
    const router = renderTab([
      row("s1", "Asha"),
      row("s2", "Ravi", {
        tutor_consent_at: "2026-11-11T06:00:00Z",
        tutor_consent_form: "2026-11-v1",
      }),
      row("s3", "Gita", { status: "deactivated", erase_due_at: "2026-11-18T06:00:00Z" }),
    ]);
    const user = userEvent.setup();
    expect(await screen.findByText(/^Recorded/)).toHaveAttribute(
      "title",
      "Form version 2026-11-v1",
    );
    expect(screen.getByText(/Erasure after 18 Nov 2026/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Print consent forms/ })).toHaveAttribute(
      "href",
      "/classes/c1/consent-forms",
    );

    const chip = screen.getByRole("button", { name: "Without consent (2)" });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Ravi")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Select all students" }));
    const bar = screen.getByRole("region", { name: "Selected students" });
    expect(bar).toHaveTextContent("2 students selected");
    await user.click(within(bar).getByRole("link", { name: /Print consent forms/ }));
    expect(router.state.location.pathname).toBe("/classes/c1/consent-forms");
    expect(router.state.location.search).toBe("?students=s1,s3");
  });

  it("shows the empty state without the bulk bar for an empty class", async () => {
    renderTab([]);
    expect(await screen.findByText("No students yet")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Without consent/ })).not.toBeInTheDocument();
  });
});
