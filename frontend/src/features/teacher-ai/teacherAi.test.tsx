import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ getAccessToken: async () => "token", signOut: async () => {} }));

import { MisconceptionList } from "@/features/dashboard/MisconceptionList";
import { renderAt } from "@/features/xp/testUtils";
import type { MisconceptionStat, SummaryState, TeacherSummary } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

import { copyText, timeAgo } from "./copyText";
import { factHref, resourceHref } from "./links";
import { SummaryCard } from "./SummaryCard";

const SUMMARY: TeacherSummary = {
  id: "sum1",
  kind: "class",
  window: "7d",
  status: "ok",
  created_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  created_by_name: "Ms Rao",
  claims: [
    { text: "Linear equations is the weakest concept.", citations: ["F2"] },
    { text: "Asha Rao is stuck on it.", citations: ["F2", "F5"] },
  ],
  notes: [
    {
      focus: "Linear equations: moving terms",
      why: { text: "Most failures are on moving terms.", citations: ["F5"] },
      revisit: [
        {
          id: "R2",
          kind: "worked_example",
          title: "Moving terms",
          concept: "maths/lin",
          concept_title: "Linear equations",
          kp: "moving",
          available: true,
          in_course: true,
        },
      ],
      group: [{ student_id: "s1", display_name: "Asha Rao" }],
      assign: { concepts: ["maths/lin"], student_ids: ["s1"] },
    },
  ],
  facts: [
    {
      id: "F2",
      text: "Concept 'Linear equations': 6 of 14 KP tries failed (43%).",
      link: {
        kind: "concept",
        concept: "maths/lin",
        id: null,
        student_id: null,
        card: null,
        section: null,
      },
    },
    {
      id: "F5",
      text: "Prerequisite 'Integers' is the open cause for 1 students stuck (Asha Rao).",
      link: {
        kind: "concept",
        concept: "maths/lin",
        id: null,
        student_id: null,
        card: null,
        section: null,
      },
    },
  ],
};

function state(overrides: Partial<SummaryState> = {}): SummaryState {
  return {
    enabled: true,
    enough_data: true,
    summary: null,
    stale: false,
    can_regenerate: true,
    blocked: null,
    daily_left: 10,
    resets_at: "2026-11-06T18:30:00Z",
    ...overrides,
  };
}

const GET = "GET /api/v1/classes/c1/summary";
const POST = "POST /api/v1/classes/c1/summary";

function mount(handlers: Record<string, (init: RequestInit) => Response>, onAssign = vi.fn()) {
  vi.stubGlobal("fetch", vi.fn(routeFetch(handlers)));
  const { router } = renderAt(
    <SummaryCard classId="c1" window="7d" classCourse="maths" onAssign={onAssign} />,
    "/classes/c1",
    "/classes/:id",
  );
  return { router, onAssign };
}

describe("SummaryCard", () => {
  it("is hidden when teacher AI is off", async () => {
    mount({ [GET]: () => jsonResponse(200, state({ enabled: false })) });
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/AI summary/)).not.toBeInTheDocument());
  });

  it("generates from the empty state, showing the writing state", async () => {
    let release: (r: Response) => void = () => {};
    let generated = false;
    mount({
      [GET]: () =>
        jsonResponse(200, generated ? state({ summary: SUMMARY, blocked: "fresh" }) : state()),
      [POST]: () => {
        generated = true;
        return new Promise<Response>((r) => (release = r)) as unknown as Response;
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Generate summary/ }));
    expect(await screen.findByText(/this can take up to a minute/)).toBeInTheDocument();
    release(jsonResponse(201, SUMMARY));
    expect(await screen.findByText(/Linear equations is the weakest concept/)).toBeInTheDocument();
    expect(screen.getByText(/by Ms Rao · 2 h ago/)).toBeInTheDocument();
    expect(screen.getByText(/Written by AI from the dashboard numbers/)).toBeInTheDocument();
  });

  it("explains not enough data without a button", async () => {
    mount({
      [GET]: () =>
        jsonResponse(
          200,
          state({ enough_data: false, can_regenerate: false, blocked: "not_enough_data" }),
        ),
    });
    expect(await screen.findByText(/Not enough activity yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();
  });

  it("shows stale and partial states, and a disabled Regenerate with its reason", async () => {
    mount({
      [GET]: () =>
        jsonResponse(
          200,
          state({
            summary: { ...SUMMARY, status: "partial" },
            stale: true,
            can_regenerate: false,
            blocked: "teacher_cap",
          }),
        ),
    });
    expect(await screen.findByText("Data changed")).toBeInTheDocument();
    expect(screen.getByText("The data has changed since this summary.")).toBeInTheDocument();
    expect(screen.getByText(/Some sentences were removed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regenerate/ })).toBeDisabled();
    expect(screen.getByText(/used today's 10 summaries/)).toBeInTheDocument();
  });

  it.each([
    [429, "teacher_ai_daily_cap", /You've used today's 10 summaries/],
    [429, "school_ai_daily_cap", /Your school has used today's summaries/],
    [409, "summary_busy", /already being written/],
    [502, "summary_failed", /Couldn't write a summary this time/],
    [503, "teacher_ai_unavailable", /aren't available right now/],
  ])("shows the %s %s error", async (status, code, message) => {
    mount({
      [GET]: () => jsonResponse(200, state()),
      [POST]: () => jsonResponse(status, { code, message: "server text" }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /Generate summary/ }));
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("keeps the last summary when a regenerate fails", async () => {
    mount({
      [GET]: () => jsonResponse(200, state({ summary: SUMMARY, stale: true })),
      [POST]: () => jsonResponse(502, { code: "summary_failed", message: "x" }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /Regenerate/ }));
    expect(await screen.findByText(/Couldn't write a summary/)).toBeInTheDocument();
    expect(screen.getByText(/Linear equations is the weakest concept/)).toBeInTheDocument();
  });

  it("shows a network error with Try again", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init: RequestInit = {}) => {
        if ((init.method ?? "GET") === "POST") throw new TypeError("Failed to fetch");
        return jsonResponse(200, state());
      }),
    );
    renderAt(
      <SummaryCard classId="c1" window="7d" classCourse="maths" onAssign={vi.fn()} />,
      "/classes/c1",
      "/classes/:id",
    );
    fireEvent.click(await screen.findByRole("button", { name: /Generate summary/ }));
    expect(await screen.findByText(/Couldn't reach the server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("opens a citation and links to its source", async () => {
    const { router } = mount({ [GET]: () => jsonResponse(200, state({ summary: SUMMARY })) });
    const [chip] = await screen.findAllByRole("button", { name: "Source 1" });
    fireEvent.click(chip!);
    expect(await screen.findByText(/6 of 14 KP tries failed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: /Open/ }));
    await waitFor(() =>
      expect(router.state.location.search).toBe(`?concept=${encodeURIComponent("maths/lin")}`),
    );
  });

  it("assigns a note to its group, prefilled", async () => {
    const { onAssign } = mount({ [GET]: () => jsonResponse(200, state({ summary: SUMMARY })) });
    fireEvent.click(await screen.findByRole("button", { name: "Assign to these students" }));
    expect(onAssign).toHaveBeenCalledWith({ concepts: ["maths/lin"], student_ids: ["s1"] });
    fireEvent.click(screen.getByRole("button", { name: "Assign to class" }));
    expect(onAssign).toHaveBeenLastCalledWith({ concepts: ["maths/lin"], student_ids: null });
    const link = screen.getByRole("link", { name: "KP: Moving terms" });
    expect(link).toHaveAttribute("href", "/learn/maths/maths/lin?step=kp%3Amoving");
  });

  it("disables Assign for a prerequisite in another course", async () => {
    const note = {
      ...SUMMARY.notes[0]!,
      assign: { concepts: [], student_ids: ["s1"] },
    };
    mount({
      [GET]: () => jsonResponse(200, state({ summary: { ...SUMMARY, notes: [note] } })),
    });
    expect(await screen.findByText("This prerequisite is in another course")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign to class" })).toBeDisabled();
  });
});

describe("copy text and links", () => {
  it("copies names and no chip numbers", () => {
    const text = copyText(SUMMARY);
    expect(text).toContain("- Asha Rao is stuck on it.");
    expect(text).toContain("Group: Asha Rao");
    expect(text).toContain("Revisit: KP: Moving terms");
    expect(text).not.toMatch(/\[\d\]|F\d/);
  });

  it("formats relative times", () => {
    const now = new Date("2026-11-05T12:00:00Z");
    expect(timeAgo("2026-11-05T11:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-11-05T11:55:00Z", now)).toBe("5 min ago");
    expect(timeAgo("2026-11-04T12:00:00Z", now)).toBe("1 day ago");
  });

  it("routes each fact kind", () => {
    const base = { concept: null, id: null, student_id: null, card: null, section: null };
    const ctx = { classId: "c1", window: "30d" as const, studentId: "s1" };
    expect(factHref({ ...base, kind: "concept", concept: "m/lin" }, ctx)).toBe(
      "/classes/c1?window=30d&concept=m%2Flin",
    );
    expect(factHref({ ...base, kind: "misconception", id: "m1" }, ctx)).toBe(
      "/classes/c1?window=30d&misconception=m1",
    );
    expect(factHref({ ...base, kind: "student", student_id: "s2" }, ctx)).toBe(
      "/classes/c1/students/s2",
    );
    expect(factHref({ ...base, kind: "student" }, ctx)).toBeNull();
    expect(factHref({ ...base, kind: "assignment", id: "a1" }, ctx)).toBe(
      "/classes/c1/assignments?assignment=a1",
    );
    expect(factHref({ ...base, kind: "student_section", section: "graph" }, ctx)).toBe(
      "/classes/c1/students/s1#graph",
    );
    expect(
      factHref({ ...base, kind: "overview_card", card: "hints" }, { ...ctx, window: "7d" }),
    ).toBe("/classes/c1#hints");
    const retired = { ...SUMMARY.notes[0]!.revisit[0]!, available: false };
    expect(resourceHref(retired, "maths")).toBeNull();
  });
});

describe("MisconceptionList openId", () => {
  it("expands the linked row", () => {
    const rows: MisconceptionStat[] = [
      {
        id: "m1",
        title: "Sign stays the same",
        concept: "maths/lin",
        concept_title: "Linear equations",
        chosen: 2,
        offered: 4,
        rate: 0.5,
        students: 2,
        items: [{ prompt: "Solve x + 2 = 5", chosen_text: "x = 7", student_names: ["Asha"] }],
      },
    ];
    const router = createMemoryRouter(
      [{ path: "/", element: <MisconceptionList rows={rows} openId="m1" /> }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(screen.getByText("Solve x + 2 = 5")).toBeInTheDocument();
  });
});
