import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { renderAt } from "@/features/xp/testUtils";
import { todayIst } from "@/lib/dates";
import type { ClassStudent, MyAssignment, Outline, OutlineConcept } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

import { AssignedCard } from "./AssignedCard";
import { AssignmentDialog } from "./AssignmentDialog";

function concept(id: string, title: string): OutlineConcept {
  return {
    id,
    title,
    summary: "",
    status: null,
    prereqs: [],
    kps_passed: 0,
    kps_total: 3,
    parts_passed: 0,
    parts_total: 3,
    waiting: null,
    brush_up: false,
    brush_up_id: null,
  };
}

const many = Array.from({ length: 11 }, (_, i) => concept(`maths/c${i}`, `Concept ${i}`));
const outline: Outline = {
  course: { slug: "maths", title: "Maths", subject: "maths" },
  chapters: [
    {
      slug: "ch1",
      title: "Chapter one",
      grade: 9,
      // A borrowed cross-course prerequisite is left out of the picker.
      concepts: [concept("physics/borrowed", "Borrowed"), ...many.slice(0, 3)],
    },
    { slug: "ch2", title: "Chapter two", grade: 9, concepts: many.slice(3) },
  ],
};

const students: ClassStudent[] = ["Asha", "Ravi", "Gone"].map((name, i) => ({
  id: `s${i}`,
  display_name: name,
  username: name.toLowerCase(),
  status: i === 2 ? "deactivated" : "active",
  week_xp: 0,
  streak_days: 0,
  reviews_due: 0,
  last_quiz: null,
  at_risk: [],
}));

function mockDialog(post: (init: RequestInit) => Response) {
  const fetch = vi.fn(
    routeFetch({
      "GET /api/v1/learn/courses/maths/outline": () => jsonResponse(200, outline),
      "GET /api/v1/classes/c1/students": () => jsonResponse(200, students),
      "POST /api/v1/classes/c1/assignments": post,
    }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("AssignmentDialog", () => {
  it("selects a chapter, caps at 10 concepts and limits the date", async () => {
    mockDialog(() => jsonResponse(201, {}));
    renderAt(
      <AssignmentDialog
        classId="c1"
        courseSlug="maths"
        draft={{ concepts: [] }}
        onClose={vi.fn()}
      />,
    );
    await screen.findByText("Chapter one");
    expect(screen.queryByText("Borrowed")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "All of Chapter one" }));
    expect(screen.getByText("3 of 10")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "All of Chapter two" }));
    expect(screen.getByText("10 of 10")).toBeInTheDocument();
    // The 11th concept can't be picked.
    expect(screen.getByRole("checkbox", { name: "Concept 10" })).toBeDisabled();
    expect(screen.getByLabelText("Due date")).toHaveAttribute("min", todayIst());
  });

  it("sends chosen students and shows server errors", async () => {
    const fetch = mockDialog(() =>
      jsonResponse(422, {
        code: "students_not_in_class",
        message: "Some students aren't in this class.",
      }),
    );
    renderAt(
      <AssignmentDialog
        classId="c1"
        courseSlug="maths"
        draft={{ concepts: ["maths/c0"] }}
        onClose={vi.fn()}
      />,
    );
    await screen.findByText("Chapter one");
    fireEvent.click(screen.getByLabelText("Choose students"));
    // Only active students can be chosen.
    expect(screen.queryByRole("checkbox", { name: "Gone" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search students"), { target: { value: "ra" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Ravi" }));
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Some students aren't in this class.",
    );
    const post = fetch.mock.calls.find(([, init]) => init?.method === "POST");
    const body = JSON.parse(String(post?.[1]?.body));
    expect(body).toMatchObject({ concepts: ["maths/c0"], student_ids: ["s1"], note: null });
  });

  it("validates before sending", async () => {
    const fetch = mockDialog(() => jsonResponse(201, {}));
    renderAt(
      <AssignmentDialog
        classId="c1"
        courseSlug="maths"
        draft={{ concepts: [] }}
        onClose={vi.fn()}
      />,
    );
    await screen.findByText("Chapter one");
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Pick 1 to 10 concepts.");
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
});

function mine(overrides: Partial<MyAssignment> = {}): MyAssignment {
  return {
    id: "a1",
    title: "Speed + 1 more",
    class_name: "9B Physics",
    course: "physics",
    due_date: "2026-11-08",
    note: "Before Friday's test",
    status: "in_progress",
    done_at: null,
    learned: 1,
    total: 2,
    path: Array.from({ length: 7 }, (_, i) => ({
      concept: `physics/p${i}`,
      course: "physics",
      title: `Step ${i}`,
      status: i === 0 ? ("in_progress" as const) : ("locked" as const),
      waiting: false,
      target: i === 6,
    })),
    next: { concept: "physics/p0", course: "physics", title: "Step 0", brush_up_id: null },
    ...overrides,
  };
}

function mockMine(response: () => Response) {
  vi.stubGlobal("fetch", vi.fn(routeFetch({ "GET /api/v1/me/assignments": response })));
}

describe("AssignedCard", () => {
  it("shows the path (max 5 + N more), the note and Continue", async () => {
    mockMine(() => jsonResponse(200, [mine()]));
    renderAt(<AssignedCard />);
    const card = (await screen.findByRole("heading", { name: "Assigned by your teacher" })).closest(
      "section",
    )!;
    expect(within(card).getByText("Before Friday's test")).toBeInTheDocument();
    expect(within(card).getByText("1 of 2 concepts")).toBeInTheDocument();
    expect(within(card).getByText("Step 4")).toBeInTheDocument();
    expect(within(card).queryByText("Step 5")).not.toBeInTheDocument();
    expect(within(card).getByText("+ 2 more")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Continue: Step 0" })).toHaveAttribute(
      "href",
      "/learn/physics/physics/p0",
    );
  });

  it("shows overdue, done and waiting states", async () => {
    mockMine(() =>
      jsonResponse(200, [
        mine({ id: "a1", status: "overdue", due_date: "2026-11-03" }),
        mine({
          id: "a2",
          status: "done_on_time",
          done_at: "2026-11-06T10:00:00Z",
          path: [],
          next: null,
        }),
        mine({ id: "a3", next: null }),
      ]),
    );
    renderAt(<AssignedCard />);
    expect(await screen.findByText(/Overdue since 3 Nov/)).toBeInTheDocument();
    expect(screen.getByText(/Done ✓ 6 Nov/)).toBeInTheDocument();
    expect(
      screen.getByText("Waiting: retry tomorrow, or learn something else."),
    ).toBeInTheDocument();
  });

  it("links a due brush-up first", async () => {
    mockMine(() =>
      jsonResponse(200, [
        mine({
          next: { concept: "physics/p0", course: "physics", title: "Step 0", brush_up_id: "r1" },
        }),
      ]),
    );
    renderAt(<AssignedCard />);
    expect(await screen.findByRole("link", { name: "Brush up first: Step 0" })).toHaveAttribute(
      "href",
      "/learn/brush-up/r1",
    );
  });

  it("is hidden when empty or on error", async () => {
    mockMine(() => jsonResponse(500, { code: "error" }));
    renderAt(<AssignedCard />);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(screen.queryByText("Assigned by your teacher")).not.toBeInTheDocument();
  });
});
