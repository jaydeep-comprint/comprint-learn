import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import type { ClassContext } from "@/features/dashboard/classContext";
import { renderAt } from "@/features/xp/testUtils";
import type {
  ClassStudent,
  DiagnosticResult,
  DiagnosticState,
  PlacementOverview,
  Question,
  SchoolClass,
} from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

import { PlacementCard } from "./PlacementCard";
import { PlacementPage } from "./PlacementPage";
import { PlacementResult } from "./PlacementResult";
import { PlacementTab } from "./PlacementTab";

const cls: SchoolClass = {
  id: "c1",
  name: "9A",
  subject: "maths",
  grade: 9,
  archived: false,
  student_count: 2,
  teachers: [],
  daily_goal: 15,
  leaderboard_enabled: false,
};

const students: ClassStudent[] = [
  {
    id: "s1",
    display_name: "Aarav",
    username: "aarav",
    status: "active",
    week_xp: 0,
    streak_days: 0,
    reviews_due: 0,
    last_quiz: null,
    at_risk: [],
    tutor_consent_at: null,
    tutor_consent_form: null,
    erase_due_at: null,
  },
  {
    id: "s2",
    display_name: "Bina",
    username: "bina",
    status: "active",
    week_xp: 0,
    streak_days: 0,
    reviews_due: 0,
    last_quiz: null,
    at_risk: [],
    tutor_consent_at: null,
    tutor_consent_form: null,
    erase_due_at: null,
  },
];

function overview(overrides: Partial<PlacementOverview> = {}): PlacementOverview {
  return {
    course: { slug: "maths-9-10", title: "Maths", subject: "maths" },
    archived: false,
    chapters: [
      { id: "ch1", slug: "lin", title: "Linear equations", grade: 9, covered: false },
      { id: "ch2", slug: "pair", title: "Pairs of equations", grade: 10, covered: true },
    ],
    range: { concepts: 3, prereqs: 1, askable: 3 },
    students: [
      {
        student_id: "s1",
        display_name: "Aarav",
        status: "finished",
        diagnostic_id: "d1",
        sent_at: "2026-11-07T09:00:00Z",
        started_at: "2026-11-07T09:01:00Z",
        finished_at: "2026-11-07T09:20:00Z",
        answered: 9,
        result_at: "2026-11-07T09:20:00Z",
        counts: { learned: 5, conditional: 2, demoted: 1 },
      },
      {
        student_id: "s2",
        display_name: "Bina",
        status: "active",
        diagnostic_id: "d2",
        sent_at: "2026-11-07T09:00:00Z",
        started_at: "2026-11-07T09:05:00Z",
        finished_at: null,
        answered: 7,
        result_at: null,
        counts: null,
      },
    ],
    ...overrides,
  };
}

function renderTab(
  data: PlacementOverview,
  extra: Record<string, (init: RequestInit) => Response> = {},
) {
  const fetch = vi.fn(
    routeFetch({
      "GET /api/v1/classes/c1/placement": () => jsonResponse(200, data),
      "GET /api/v1/classes/c1/students": () => jsonResponse(200, students),
      ...extra,
    }),
  );
  vi.stubGlobal("fetch", fetch);
  const context: ClassContext = { cls, courseSlug: "maths-9-10" };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      {
        path: "/classes/:id",
        element: <Outlet context={context} />,
        children: [{ path: "placement", element: <PlacementTab /> }],
      },
    ],
    { initialEntries: ["/classes/c1/placement"] },
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { fetch, router };
}

const body = (fetch: ReturnType<typeof vi.fn>, method: string, path: string) => {
  const call = fetch.mock.calls.find(
    ([url, init]) =>
      String(url).endsWith(path) && (init as RequestInit | undefined)?.method === method,
  );
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
};

describe("PlacementTab", () => {
  it("shows chapters, the range preview and student statuses", async () => {
    renderTab(overview());
    expect(await screen.findByText("Covered chapters")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Pairs of equations" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Linear equations" })).not.toBeChecked();
    expect(
      screen.getByText(/3 concepts will be checked \(1 of them prerequisites/),
    ).toBeInTheDocument();
    expect(screen.getByText("In progress (7 answered)")).toBeInTheDocument();
    expect(screen.getByText("learned 5 · conditional 2 · demoted 1")).toBeInTheDocument();
  });

  it("saves ticked chapters", async () => {
    const saved = overview({
      chapters: overview().chapters.map((c) => ({ ...c, covered: true })),
    });
    const { fetch } = renderTab(overview(), {
      "PUT /api/v1/classes/c1/placement/chapters": () => jsonResponse(200, saved),
    });
    const save = await screen.findByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Linear equations" }));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.click(save);
    await waitFor(() =>
      expect(body(fetch, "PUT", "/placement/chapters")).toEqual({ chapter_ids: ["ch2", "ch1"] }),
    );
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument());
  });

  it("sends to the whole class", async () => {
    const { fetch } = renderTab(overview(), {
      "POST /api/v1/classes/c1/placement/send": () => jsonResponse(200, { sent: 1, skipped: 1 }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Send placement check" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(body(fetch, "POST", "/placement/send")).toEqual({ all_students: true }),
    );
  });

  it("disables Send with a hint until a chapter is ticked", async () => {
    renderTab(overview({ chapters: overview().chapters.map((c) => ({ ...c, covered: false })) }));
    expect(await screen.findByRole("button", { name: "Send placement check" })).toBeDisabled();
    expect(screen.getByText(/Tick and save a covered chapter/)).toBeInTheDocument();
  });

  it("offers Cancel for an open check and Re-send for a finished one", async () => {
    const user = userEvent.setup();
    const { fetch } = renderTab(overview(), {
      "POST /api/v1/classes/c1/placement/students/s2/cancel": () =>
        jsonResponse(200, { ...overview().students[1], status: "cancelled" }),
    });
    await user.click(await screen.findByRole("button", { name: "Actions for Aarav" }));
    expect(await screen.findByRole("menuitem", { name: "Re-send" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Cancel" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Actions for Bina" }));
    await user.click(await screen.findByRole("menuitem", { name: "Cancel" }));
    await user.click(await screen.findByRole("button", { name: "Cancel check" }));
    await waitFor(() =>
      expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/students/s2/cancel"))).toBe(
        true,
      ),
    );
  });

  it("shows the no-course and no-students empty states", async () => {
    renderTab(overview({ course: null }));
    expect(await screen.findByText("This class has no course yet")).toBeInTheDocument();
  });

  it("links to the roster when the class has no students", async () => {
    renderTab(overview({ students: [] }));
    expect(await screen.findByRole("link", { name: "Go to the roster" })).toHaveAttribute(
      "href",
      "/classes/c1/students",
    );
  });
});

const sent: DiagnosticState = {
  id: "d1",
  status: "sent",
  class_name: "9A",
  course: { slug: "maths-9-10", title: "Maths", subject: "maths" },
  answered: 0,
  max_questions: 25,
  empty: false,
};

describe("PlacementCard", () => {
  it("shows Start or Continue per open check", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/diagnostics/current": () =>
            jsonResponse(200, [
              sent,
              {
                ...sent,
                id: "d2",
                status: "active",
                answered: 7,
                class_name: "9B",
                course: { slug: "physics-9-10", title: "Physics", subject: "physics" },
              },
            ]),
        }),
      ),
    );
    renderAt(<PlacementCard />);
    expect(await screen.findByText("Placement check · Maths")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute("href", "/placement/d1");
    expect(screen.getByRole("link", { name: "Continue (7 answered)" })).toBeInTheDocument();
  });

  it("names the class when two checks share a subject", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/diagnostics/current": () =>
            jsonResponse(200, [sent, { ...sent, id: "d2", class_name: "9B" }]),
        }),
      ),
    );
    renderAt(<PlacementCard />);
    expect(await screen.findByText("Placement check · Maths (9A)")).toBeInTheDocument();
    expect(screen.getByText("Placement check · Maths (9B)")).toBeInTheDocument();
  });

  it("renders nothing with no open check", async () => {
    const fetch = vi.fn(
      routeFetch({ "GET /api/v1/diagnostics/current": () => jsonResponse(200, []) }),
    );
    vi.stubGlobal("fetch", fetch);
    renderAt(<PlacementCard />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByText(/Placement check/)).not.toBeInTheDocument();
  });
});

function question(position: number): Question {
  return {
    session_id: "ps1",
    position,
    item_id: `i${position}`,
    type: "mcq",
    prompt_md: `Question text ${position}`,
    unit: null,
    options: [
      { id: "1", text: "First" },
      { id: "2", text: "Second" },
    ],
    variables: null,
    results: [],
    preview_seed: null,
  };
}

describe("PlacementPage", () => {
  function mock(initial: DiagnosticState, finishAt = 3) {
    let state = initial;
    let position = 1;
    const answers: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/diagnostics/d1": () => jsonResponse(200, state),
          "POST /api/v1/diagnostics/d1/start": () => {
            state = { ...state, status: "active" };
            return jsonResponse(200, state);
          },
          "GET /api/v1/diagnostics/d1/question": () => jsonResponse(200, question(position)),
          "POST /api/v1/diagnostics/d1/answer": (init) => {
            answers.push(JSON.parse(String(init.body)));
            const finished = position >= finishAt;
            position += 1;
            return jsonResponse(200, { finished, answered: position - 1 });
          },
        }),
      ),
    );
    return answers;
  }

  it("starts, answers with no feedback, and supports I don't know", async () => {
    const user = userEvent.setup();
    const answers = mock(sent, 2);
    const { router } = renderAt(<PlacementPage />, "/placement/d1", "/placement/:id");
    await user.click(await screen.findByRole("button", { name: "Start" }));
    expect(await screen.findByText("Question 1 · at most 25")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "First" }));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Question 2 · at most 25")).toBeInTheDocument();
    expect(screen.queryByText(/correct|wrong/i)).not.toBeInTheDocument();
    expect(answers[0]).toMatchObject({ position: 1, response: "1", session_id: "ps1" });
    await user.click(screen.getByRole("button", { name: "I don't know" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/placement/d1/result"));
    expect(answers[1]).toMatchObject({ position: 2, idk: true, session_id: "ps1" });
  });

  it("pauses back home on the same question", async () => {
    const user = userEvent.setup();
    mock({ ...sent, status: "active", answered: 4 });
    const { router } = renderAt(<PlacementPage />, "/placement/d1", "/placement/:id");
    expect(await screen.findByText("Question 1 · at most 25")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("says when the teacher cancelled it", async () => {
    mock({ ...sent, status: "cancelled" });
    renderAt(<PlacementPage />, "/placement/d1", "/placement/:id");
    expect(
      await screen.findByText("Your teacher cancelled this placement check."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back home" })).toHaveAttribute("href", "/");
  });
});

describe("PlacementResult", () => {
  it("lists learned, to check soon and to learn", async () => {
    const result: DiagnosticResult = {
      answered: 9,
      learned: [{ id: "m/a", title: "Alpha" }],
      conditional: [{ id: "m/b", title: "Beta" }],
      to_learn: [{ id: "m/c", title: "Gamma" }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/diagnostics/d1": () => jsonResponse(200, { ...sent, status: "finished" }),
          "GET /api/v1/diagnostics/d1/result": () => jsonResponse(200, result),
        }),
      ),
    );
    renderAt(<PlacementResult />, "/placement/d1/result", "/placement/:id/result");
    expect(await screen.findByText("You placed out of 2 concepts")).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Learned" })).getByText("Alpha"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "To check soon" })).getByText("Beta"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "To learn" })).getByText("Gamma"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See your knowledge map" })).toHaveAttribute(
      "href",
      "/learn/maths-9-10",
    );
  });
});
