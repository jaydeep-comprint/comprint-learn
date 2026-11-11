import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createFakeSupabase, fakeSession } from "@/test/fakeSupabase";
import { adminMe, jsonResponse, renderRoutes, routeFetch, teacherMe } from "@/test/render";
import type { AuditEvent, ClassStudent, Notice, SchoolClass, Student } from "@/lib/types";

const fake = vi.hoisted(() => ({ current: null as ReturnType<typeof createFakeSupabase> | null }));
vi.mock("@/lib/supabase", () => ({
  getSupabase: () => fake.current!.client,
  getAccessToken: async () => "token-123",
  signOut: async () => {},
}));
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast: toasts }));

import { StudentsPage } from "@/features/students/StudentsPage";

import { AuditPage } from "./AuditPage";
import { ConsentFormsView } from "./ConsentFormsView";

const notice: Notice = {
  version: "2026-11-v1",
  title: "AI tutor: notice and consent form",
  body_md: "## About the AI tutor\n\nThe tutor uses DeepSeek.",
  stores_md: "## What this app stores about you\n\n- Your account",
};

const privacy = { tutor_consent_at: null, tutor_consent_form: null, erase_due_at: null };

function student(id: string, name: string, extra: Partial<Student> = {}): Student {
  return {
    id,
    display_name: name,
    username: name.toLowerCase(),
    status: "active",
    class_ids: [],
    ...privacy,
    ...extra,
  };
}

function classStudent(id: string, name: string, extra: Partial<ClassStudent> = {}): ClassStudent {
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
    ...privacy,
    ...extra,
  };
}

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

beforeEach(() => {
  fake.current = createFakeSupabase();
  fake.current.state.session = fakeSession();
  Object.values(toasts).forEach((f) => f.mockReset());
});

describe("consent bulk bar (school Students page, admin)", () => {
  it("records consent for the selected students after the confirmation", async () => {
    let consented = false;
    const posts: unknown[] = [];
    const listed = () => [
      student("s1", "Asha", consented ? { tutor_consent_at: "2026-11-11T06:00:00Z" } : {}),
      student("s2", "Ravi", consented ? { tutor_consent_at: "2026-11-11T06:00:00Z" } : {}),
      student("s3", "Gita"),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/me": () => jsonResponse(200, adminMe),
          "GET /api/v1/students": () => jsonResponse(200, listed()),
          "GET /api/v1/classes": () => jsonResponse(200, []),
          "GET /api/v1/privacy/notice": () => jsonResponse(200, notice),
          "POST /api/v1/students/consent": (init) => {
            posts.push(JSON.parse(String(init.body)));
            consented = true;
            return jsonResponse(200, listed());
          },
        }),
      ),
    );
    renderRoutes([{ path: "/students", element: <StudentsPage /> }], "/students");
    const user = userEvent.setup();

    expect(await screen.findAllByText("Not recorded")).toHaveLength(3);
    await user.click(await screen.findByRole("checkbox", { name: "Select Asha" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Ravi" }));
    const bar = screen.getByRole("region", { name: "Selected students" });
    expect(bar).toHaveTextContent("2 students selected");

    await user.click(within(bar).getByRole("button", { name: /Record consent/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(
      "I confirm the school holds a signed consent form (version 2026-11-v1) from a parent or guardian of each selected student.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Record consent" }));

    await waitFor(() => expect(screen.getAllByText(/^Recorded/)).toHaveLength(2));
    expect(posts).toEqual([{ student_ids: ["s1", "s2"], action: "record" }]);
    expect(toasts.success).toHaveBeenCalledWith("Consent recorded for 2 students");
    expect(screen.queryByRole("region", { name: "Selected students" })).not.toBeInTheDocument();
  });

  it("shows the server's error and keeps the selection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/me": () => jsonResponse(200, adminMe),
          "GET /api/v1/students": () => jsonResponse(200, [student("s1", "Asha")]),
          "GET /api/v1/classes": () => jsonResponse(200, []),
          "GET /api/v1/privacy/notice": () => jsonResponse(200, notice),
          "POST /api/v1/students/consent": () =>
            jsonResponse(422, {
              code: "consent_not_allowed",
              message: "Consent can't be recorded for a student whose erasure is pending.",
            }),
        }),
      ),
    );
    renderRoutes([{ path: "/students", element: <StudentsPage /> }], "/students");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: "Select Asha" }));
    await user.click(screen.getByRole("button", { name: /Record consent/ }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Record consent",
      }),
    );
    await waitFor(() =>
      expect(toasts.error).toHaveBeenCalledWith(
        "Consent can't be recorded for a student whose erasure is pending.",
      ),
    );
    expect(screen.getByRole("region", { name: "Selected students" })).toBeInTheDocument();
  });

  it("is not offered to teachers on the school page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/me": () => jsonResponse(200, teacherMe),
          "GET /api/v1/students": () => jsonResponse(200, [student("s1", "Asha")]),
          "GET /api/v1/classes": () => jsonResponse(200, []),
        }),
      ),
    );
    renderRoutes([{ path: "/students", element: <StudentsPage /> }], "/students");
    expect(await screen.findByText("Not recorded")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});

describe("ConsentFormsView", () => {
  const roster = [
    classStudent("s1", "Asha"),
    classStudent("s2", "Ravi", { tutor_consent_at: "2026-11-11T06:00:00Z" }),
    classStudent("s3", "Gita", { status: "deactivated" }),
    classStudent("s4", "Mina"),
  ];
  const stub = (students: ClassStudent[]) =>
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/me": () => jsonResponse(200, teacherMe),
          "GET /api/v1/classes/c1": () => jsonResponse(200, cls),
          "GET /api/v1/classes/c1/students": () => jsonResponse(200, students),
          "GET /api/v1/privacy/notice": () => jsonResponse(200, notice),
        }),
      ),
    );
  const routes = [
    { path: "/classes/:id/consent-forms", element: <ConsentFormsView /> },
    { path: "/classes/:id/students", element: <p>Students tab</p> },
  ];

  it("prints one page per active student without consent by default", async () => {
    stub(roster);
    renderRoutes(routes, "/classes/c1/consent-forms");
    const forms = await screen.findAllByRole("article");
    expect(forms.map((f) => f.getAttribute("aria-label"))).toEqual([
      "Consent form for Asha",
      "Consent form for Mina",
    ]);
    expect(forms[0]).toHaveClass("consent-form");
    expect(forms[0]).toHaveTextContent("Test School · 9A Maths");
    expect(forms[0]).toHaveTextContent("The tutor uses DeepSeek.");
    expect(forms[0]).toHaveTextContent("Parent or guardian name");
    expect(forms[0]).toHaveTextContent("Form version 2026-11-v1");
    expect(forms[0]).not.toHaveTextContent("What this app stores");
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();
  });

  it("prints the chosen students, even with consent, and ignores unknown ids", async () => {
    stub(roster);
    renderRoutes(routes, "/classes/c1/consent-forms?students=s2,nope,s3");
    const forms = await screen.findAllByRole("article");
    expect(forms.map((f) => f.getAttribute("aria-label"))).toEqual([
      "Consent form for Ravi",
      "Consent form for Gita",
    ]);
  });

  it("says so when everyone already has consent", async () => {
    stub([roster[1]!]);
    renderRoutes(routes, "/classes/c1/consent-forms");
    expect(
      await screen.findByText("Every student in this class already has consent recorded."),
    ).toBeInTheDocument();
  });
});

describe("AuditPage", () => {
  const event = (id: string, extra: Partial<AuditEvent> = {}): AuditEvent => ({
    id,
    action: "consent_recorded",
    at: "2026-11-11T06:00:00Z",
    actor: { id: "t1", display_name: "Ms Rao" },
    target: { id: "s1", display_name: "Asha" },
    meta: { form: "2026-11-v1" },
    ...extra,
  });

  it("shows the empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "GET /api/v1/audit": () => jsonResponse(200, { items: [], next_before: null }),
        }),
      ),
    );
    renderRoutes([{ path: "/audit", element: <AuditPage /> }], "/audit");
    expect(await screen.findByText("Nothing recorded yet.")).toBeInTheDocument();
  });

  it("filters by action and loads more pages", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        urls.push(url);
        if (url.includes("before=cursor-1")) {
          return jsonResponse(200, {
            items: [event("e2", { actor: null, action: "erase_completed", meta: {} })],
            next_before: null,
          });
        }
        return jsonResponse(200, { items: [event("e1")], next_before: "cursor-1" });
      }),
    );
    renderRoutes([{ path: "/audit", element: <AuditPage /> }], "/audit");
    const user = userEvent.setup();

    expect(await screen.findByText("Ms Rao")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Consent recorded" })).toBeInTheDocument();
    expect(screen.getByText("form 2026-11-v1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("System")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Student erased" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Action" }), "password_reset");
    await waitFor(() => expect(urls.at(-1)).toBe("/api/v1/audit?action=password_reset"));
  });
});
