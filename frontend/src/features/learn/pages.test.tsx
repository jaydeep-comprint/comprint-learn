import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { CoursePage } from "@/features/learn/CoursePage";
import { LessonPage } from "@/features/learn/LessonPage";
import type { Lesson, Outline } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const COURSE = "physics-9-10";
const DIST = `${COURSE}/distance-and-displacement`;
const LESSON_URL = `/api/v1/learn/concepts/${DIST}`;
const OUTLINE_URL = `/api/v1/learn/courses/${COURSE}/outline`;

function lesson(overrides: Partial<Lesson> = {}): Lesson {
  return {
    id: DIST,
    title: "Distance and displacement",
    summary: "",
    asset_base: "",
    intro_md: "Intro text here.",
    check: {
      item_id: "i1",
      prompt: "Which has a direction?",
      options: [
        { id: "a", text: "Displacement" },
        { id: "b", text: "Distance" },
      ],
    },
    kps: [
      { slug: "kp1", title: "Along a road", worked_example_md: "Example one." },
      { slug: "kp2", title: "Around a corner", worked_example_md: "Example two." },
    ],
    steps: ["intro", "check", "kp:kp1", "kp:kp2"],
    progress: null,
    check_result: null,
    preview: false,
    ...overrides,
  };
}

const outline: Outline = {
  course: { slug: COURSE, title: "Physics", subject: "physics" },
  chapters: [
    {
      slug: "motion",
      title: "Motion",
      grade: 9,
      concepts: [
        {
          id: DIST,
          title: "Distance and displacement",
          summary: "s",
          status: "finished",
          prereqs: [],
        },
        {
          id: "maths-9-10/linear-equations-two-variables",
          title: "Linear equations in two variables",
          summary: "s",
          status: "ready",
          prereqs: [],
        },
        {
          id: `${COURSE}/speed-and-velocity`,
          title: "Speed and velocity",
          summary: "s",
          status: "locked",
          prereqs: [DIST, "maths-9-10/linear-equations-two-variables"],
        },
      ],
    },
  ],
};

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/learn/:course", element: <CoursePage /> },
      { path: "/learn/:course/:conceptCourse/:conceptSlug", element: <LessonPage /> },
    ],
    { initialEntries: [path] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const progressCalls: { step: string; active_seconds: number }[] = [];

function mockApi(l: Lesson, extra: Record<string, (init: RequestInit) => Response> = {}) {
  progressCalls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      routeFetch({
        [`GET ${LESSON_URL}`]: () => jsonResponse(200, l),
        [`GET ${OUTLINE_URL}`]: () => jsonResponse(200, outline),
        [`POST ${LESSON_URL}/progress`]: (init) => {
          const body = JSON.parse(String(init.body)) as { step: string; active_seconds: number };
          progressCalls.push(body);
          return jsonResponse(200, { seen_steps: [], last_step: body.step, finished_at: null });
        },
        ...extra,
      }),
    ),
  );
}

describe("LessonPage", () => {
  beforeEach(() => {
    progressCalls.length = 0;
  });

  it("resumes at last_step", async () => {
    mockApi(
      lesson({
        progress: {
          seen_steps: ["intro", "check", "kp:kp1"],
          last_step: "kp:kp1",
          finished_at: null,
        },
        check_result: {
          correct: true,
          chosen: "a",
          correct_option: "a",
          explanation_md: null,
          misconception: null,
        },
      }),
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByText("Worked example 1 of 2 · Along a road")).toBeInTheDocument();
    expect(screen.getByText("Example one.")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Lesson steps" });
    expect(within(nav).getByRole("button", { name: "Worked example 1" })).toHaveAttribute(
      "aria-current",
      "step",
    );
    await waitFor(() =>
      expect(progressCalls).toContainEqual({ step: "kp:kp1", active_seconds: 0 }),
    );
  });

  it("reopening a lesson in the app resumes from fresh progress, not the cached copy", async () => {
    let gets = 0;
    mockApi(lesson(), {
      [`GET ${LESSON_URL}`]: () => {
        gets += 1;
        return jsonResponse(
          200,
          gets === 1
            ? lesson()
            : lesson({
                progress: {
                  seen_steps: ["intro", "check", "kp:kp1"],
                  last_step: "kp:kp1",
                  finished_at: null,
                },
              }),
        );
      },
    });
    const router = renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByText("Intro text here.")).toBeInTheDocument();
    await act(() => router.navigate(`/learn/${COURSE}`));
    expect(await screen.findByRole("heading", { name: "Physics" })).toBeInTheDocument();
    await act(() => router.navigate(`/learn/${COURSE}/${DIST}`));
    expect(await screen.findByText("Example one.")).toBeInTheDocument();
    expect(gets).toBe(2);
  });

  it("blocks Next on the unanswered check, then finishes", async () => {
    const user = userEvent.setup();
    mockApi(lesson(), {
      [`POST ${LESSON_URL}/check`]: () =>
        jsonResponse(200, {
          correct: false,
          chosen: "b",
          correct_option: "a",
          explanation_md: "Displacement is a vector.",
          misconception: { title: "Displacement is the same as distance" },
          already_answered: false,
        }),
    });
    renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByText("Intro text here.")).toBeInTheDocument();
    // Can't jump past the check.
    const nav = screen.getByRole("navigation", { name: "Lesson steps" });
    expect(within(nav).getByRole("button", { name: "Worked example 1" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Quick check")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "Distance" }));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Not quite")).toBeInTheDocument();
    expect(
      screen.getByText("Common mix-up: Displacement is the same as distance"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Example one.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Example two.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Finish lesson" }));

    expect(await screen.findByText("Lesson finished")).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "Next up: Linear equations in two variables" }),
    ).toHaveAttribute("href", `/learn/${COURSE}/maths-9-10/linear-equations-two-variables`);
    await waitFor(() =>
      expect(progressCalls.map((c) => c.step)).toEqual(
        expect.arrayContaining(["intro", "check", "kp:kp1", "kp:kp2"]),
      ),
    );
  });

  it("staff preview: banner, every step open, nothing posted", async () => {
    mockApi(lesson({ preview: true }));
    renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByText("Teacher preview: nothing is saved")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Lesson steps" });
    expect(within(nav).getByRole("button", { name: "Worked example 2" })).toBeEnabled();
    expect(progressCalls).toEqual([]);
  });

  it("shows the locked panel for a direct URL", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          [`GET ${LESSON_URL}`]: () =>
            jsonResponse(403, {
              code: "concept_locked",
              message: "Finish first",
              prereqs: [{ id: "maths-9-10/lin", title: "Linear equations", status: "ready" }],
            }),
        }),
      ),
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByRole("heading", { name: "Finish these first" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Linear equations/ })).toHaveAttribute(
      "href",
      `/learn/${COURSE}/maths-9-10/lin`,
    );
  });
});

describe("CoursePage", () => {
  it("shows statuses and opens the locked sheet with unfinished prereqs", async () => {
    const user = userEvent.setup();
    mockApi(lesson());
    renderAt(`/learn/${COURSE}`);
    expect(await screen.findByRole("heading", { name: "Physics" })).toBeInTheDocument();
    expect(screen.getByText("1 of 3 concepts finished")).toBeInTheDocument();
    expect(screen.getByText("Class 9")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Distance and displacement/ })).toHaveAttribute(
      "href",
      `/learn/${COURSE}/${DIST}`,
    );

    await user.click(screen.getByRole("button", { name: /Speed and velocity/ }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText("Finish these first")).toBeInTheDocument();
    // Only the unfinished prerequisite is listed, linking to its lesson.
    expect(
      within(sheet).getByRole("link", { name: /Linear equations in two variables/ }),
    ).toBeInTheDocument();
    expect(within(sheet).queryByText("Distance and displacement")).toBeNull();
  });
});
