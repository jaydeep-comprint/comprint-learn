// Spec 015: a teacher's heaviest dashboard page load must use under 25% of the per-user read
// burst (120), so clicking quickly through tabs never trips the rate limit.
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClassOverview, ClassStudent, Heatmap, SchoolClass, SummaryState } from "@/lib/types";
import { createFakeSupabase, fakeSession } from "@/test/fakeSupabase";
import { jsonResponse, renderRoutes, teacherMe } from "@/test/render";

const fake = vi.hoisted(() => ({ current: null as ReturnType<typeof createFakeSupabase> | null }));
vi.mock("@/lib/supabase", () => ({
  getSupabase: () => fake.current!.client,
  getAccessToken: async () => "token-123",
  signOut: async () => {},
}));

import { routes } from "@/routes";

const READ_BURST = 120;
const MAX_GETS = READ_BURST / 4; // 30

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

const student = (id: string, name: string): ClassStudent => ({
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
});

const overview: ClassOverview = {
  window: "7d",
  students_in_scope: 2,
  has_course: true,
  weakest: [],
  at_risk: [],
  misconceptions: [],
  hints: { hints: 0, chats: 0, answered: 0, hints_per_10: null, top: [] },
  flagged: [],
  practice_share: { learn_seconds: 0, practice_seconds: 0 },
  assignments_due: [],
  overdue_assignments: 0,
};

const summary: SummaryState = {
  enabled: true,
  enough_data: false,
  summary: null,
  stale: false,
  can_regenerate: false,
  blocked: null,
  daily_left: 10,
  resets_at: "2026-11-13T00:00:00+05:30",
};

const heatmap: Heatmap = { chapters: [], students: [] };

function countingFetch() {
  const gets: string[] = [];
  const bodies: Record<string, unknown> = {
    "/api/v1/me": teacherMe,
    "/api/v1/classes/c1": cls,
    "/api/v1/classes/c1/students": [student("s1", "Asha"), student("s2", "Ravi")],
    "/api/v1/courses": [],
    "/api/v1/classes/c1/overview": overview,
    "/api/v1/classes/c1/summary": summary,
    "/api/v1/classes/c1/heatmap": heatmap,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init.method ?? "GET";
    if (method === "GET") gets.push(url);
    const body = bodies[url.split("?")[0]!];
    // Anything else answers an empty list: enough for list widgets, and still counted.
    return jsonResponse(200, body ?? []);
  });
  return { gets, fetchMock };
}

beforeEach(() => {
  fake.current = createFakeSupabase();
  fake.current.state.session = fakeSession();
});

async function settle(gets: string[]) {
  // Wait until no new request has started for a while.
  let last = -1;
  await waitFor(
    () => {
      const now = gets.length;
      const stable = now === last;
      last = now;
      expect(stable).toBe(true);
    },
    { interval: 150, timeout: 5000 },
  );
}

describe("dashboard page loads (spec 015)", () => {
  it.each([
    ["Overview", "/classes/c1", "/api/v1/classes/c1/overview"],
    ["Students tab", "/classes/c1/students", "/api/v1/classes/c1/heatmap"],
  ])("%s makes fewer than 30 GETs", async (_name, path, tabEndpoint) => {
    const { gets, fetchMock } = countingFetch();
    vi.stubGlobal("fetch", fetchMock);
    renderRoutes(routes, path);
    expect(await screen.findAllByText("9A Maths")).not.toHaveLength(0);
    await settle(gets);
    expect(gets.some((g) => g.startsWith(tabEndpoint))).toBe(true); // the tab really rendered
    expect(gets.length).toBeLessThan(MAX_GETS);
  });
});
