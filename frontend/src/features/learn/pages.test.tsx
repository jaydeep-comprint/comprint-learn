import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));
vi.mock("@/features/graph/CourseMap", () => ({
  default: () => <div>Map view stub</div>,
}));
const python = {
  status: { state: "ready" } as const,
  run: vi.fn(),
  retry: vi.fn(),
};
vi.mock("@/features/code/usePython", () => ({ usePython: () => python }));
vi.mock("@/features/code/CodeEditor", () => ({
  CodeEditor: ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <textarea
      aria-label="Code editor"
      defaultValue={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

import { CoursePage } from "@/features/learn/CoursePage";
import { resetShownAwards } from "@/features/xp/awardToast";
import { LessonPage } from "@/features/learn/LessonPage";
import type { AnswerResult, Lesson, LessonKp, Outline, Question } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const COURSE = "physics-9-10";
const DIST = `${COURSE}/distance-and-displacement`;
const LESSON_URL = `/api/v1/learn/concepts/${DIST}`;
const OUTLINE_URL = `/api/v1/learn/courses/${COURSE}/outline`;
const Q_URL = `${LESSON_URL}/kps/kp1/question`;
const PQ_URL = `${LESSON_URL}/practice/question`;
const PA_URL = `${LESSON_URL}/practice/answer`;
const A_URL = `${LESSON_URL}/kps/kp1/answer`;

function kp(slug: string, title: string, example: string, extra: Partial<LessonKp> = {}): LessonKp {
  return {
    slug,
    title,
    worked_example_md: example,
    status: "not_started",
    open: true,
    reopen_at: null,
    active: false,
    ...extra,
  };
}

function question(position: number, results: boolean[] = []): Question {
  return {
    session_id: "sess1",
    position,
    item_id: `item${position}`,
    type: "numeric",
    prompt_md: `A sprinter runs 100 m in 12.5 s (question ${position}).`,
    unit: "m/s",
    options: null,
    variables: null,
    results,
    preview_seed: null,
  };
}

function answer(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    correct: true,
    display_answer: "8 m/s",
    explanation_md: null,
    misconception: null,
    note: null,
    session_status: "active",
    already_answered: false,
    results: [true],
    concept_learned: false,
    unlocked: [],
    remediations: [],
    ...overrides,
  };
}

const ANSWERED_CHECK = {
  correct: true,
  chosen: "a",
  correct_option: "a",
  explanation_md: null,
  misconception: null,
};

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
    kps: [kp("kp1", "Along a road", "Example one."), kp("kp2", "Around a corner", "Example two.")],
    steps: ["intro", "check", "kp:kp1", "kpq:kp1", "kp:kp2", "kpq:kp2"],
    progress: null,
    check_result: null,
    preview: false,
    concept_status: "ready",
    waiting: null,
    practice: { status: "none", active: false },
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
          status: "learned",
          prereqs: [],
          kps_passed: 3,
          kps_total: 3,
          parts_passed: 3,
          parts_total: 3,
          waiting: null,
          brush_up: false,
          brush_up_id: null,
        },
        {
          id: "maths-9-10/linear-equations-two-variables",
          title: "Linear equations in two variables",
          summary: "s",
          status: "ready",
          prereqs: [],
          kps_passed: 0,
          kps_total: 3,
          parts_passed: 0,
          parts_total: 3,
          waiting: null,
          brush_up: false,
          brush_up_id: null,
        },
        {
          id: `${COURSE}/speed-and-velocity`,
          title: "Speed and velocity",
          summary: "s",
          status: "locked",
          prereqs: [DIST, "maths-9-10/linear-equations-two-variables"],
          kps_passed: 0,
          kps_total: 3,
          parts_passed: 0,
          parts_total: 3,
          waiting: null,
          brush_up: false,
          brush_up_id: null,
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
    resetShownAwards();
  });

  it("resumes at last_step", async () => {
    mockApi(
      lesson({
        progress: {
          seen_steps: ["intro", "check", "kp:kp1"],
          last_step: "kp:kp1",
          finished_at: null,
        },
        check_result: ANSWERED_CHECK,
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

  it("blocks Next on the unanswered check and on an unpassed question step", async () => {
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
      [`GET ${Q_URL}`]: () => jsonResponse(200, question(1)),
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
    expect(await screen.findByText("Practice · Along a road")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    // The step indicator can't jump past the unpassed question step either.
    expect(within(nav).getByRole("button", { name: "Worked example 2" })).toBeDisabled();
  });

  it("passing the last part shows the learned screen with what it unlocked", async () => {
    const user = userEvent.setup();
    let gets = 0;
    let posts = 0;
    mockApi(
      lesson({
        kps: [kp("kp1", "Along a road", "Example one.")],
        steps: ["intro", "check", "kp:kp1", "kpq:kp1"],
        concept_status: "in_progress",
        progress: {
          seen_steps: ["intro", "check", "kp:kp1"],
          last_step: "kp:kp1",
          finished_at: null,
        },
        check_result: ANSWERED_CHECK,
      }),
      {
        [`GET ${Q_URL}`]: () => {
          gets += 1;
          return jsonResponse(200, gets === 1 ? question(1) : question(2, [true]));
        },
        [`POST ${A_URL}`]: () => {
          posts += 1;
          return jsonResponse(
            200,
            posts === 1
              ? answer()
              : answer({
                  results: [true, true],
                  session_status: "passed",
                  concept_learned: true,
                  unlocked: [{ id: `${COURSE}/speed-and-velocity`, title: "Speed and velocity" }],
                  xp: {
                    amount: 2,
                    grade: "perfect",
                    base_minutes: "2.0",
                    hints: 0,
                    goal_met_today: false,
                  },
                }),
          );
        },
      },
    );
    const success = vi.spyOn(toast, "success");
    renderAt(`/learn/${COURSE}/${DIST}`);
    await user.click(await screen.findByRole("button", { name: "Next" }));
    expect(await screen.findByText(/question 1/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your answer"), "8");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Correct!")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next question" }));
    expect(await screen.findByText(/question 2/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your answer"), "8.0");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Part passed ✓")).toBeInTheDocument();
    expect(success).toHaveBeenCalledTimes(1);
    expect(success).toHaveBeenCalledWith("+2 XP · Perfect ×1.2", { description: undefined });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Concept learned ✓")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Speed and velocity" })).toHaveAttribute(
      "href",
      `/learn/${COURSE}/${COURSE}/speed-and-velocity`,
    );
  });

  it("a failed part shows the failed screen with the brush-up", async () => {
    const user = userEvent.setup();
    mockApi(
      lesson({
        concept_status: "in_progress",
        progress: {
          seen_steps: ["intro", "check", "kp:kp1"],
          last_step: "kpq:kp1",
          finished_at: null,
        },
        check_result: ANSWERED_CHECK,
        kps: [
          kp("kp1", "Along a road", "Example one.", { active: true, status: "in_progress" }),
          kp("kp2", "Around a corner", "Example two."),
        ],
      }),
      {
        [`GET ${Q_URL}`]: () => jsonResponse(200, question(3, [false, false])),
        [`POST ${A_URL}`]: () =>
          jsonResponse(
            200,
            answer({
              correct: false,
              results: [false, false, false],
              session_status: "failed",
              note: "Give 3 significant figures",
              remediations: [
                {
                  id: "r1",
                  kind: "review",
                  prereq: { id: "maths-9-10/lin", title: "Linear equations" },
                  concept: { id: DIST, title: "Distance and displacement" },
                },
              ],
            }),
          ),
      },
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    // An active session resumes at its question step.
    expect(await screen.findByText(/question 3/)).toBeInTheDocument();
    expect(screen.getAllByTestId("dot-wrong")).toHaveLength(2);
    await user.type(screen.getByLabelText("Your answer"), "7");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Not quite")).toBeInTheDocument();
    expect(screen.getByText("Give 3 significant figures")).toBeInTheDocument();
    expect(screen.getByText("8 m/s")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Let's come back to this")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /First, brush up on Linear equations/ }),
    ).toHaveAttribute("href", "/learn/brush-up/r1");
  });

  it("with a quiz pending, a part that would start shows the quiz panel (spec 007)", async () => {
    mockApi(
      lesson({
        concept_status: "in_progress",
        progress: {
          seen_steps: ["intro", "check", "kp:kp1", "kpq:kp1"],
          last_step: "kpq:kp1",
          finished_at: null,
        },
        check_result: ANSWERED_CHECK,
      }),
      {
        [`GET ${Q_URL}`]: () =>
          jsonResponse(409, {
            code: "quiz_pending",
            message: "Take your quiz to keep learning.",
            quiz_id: "qz1",
          }),
      },
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByText("Take your quiz to keep learning")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the quiz" })).toHaveAttribute(
      "href",
      "/quiz/qz1",
    );
  });

  it("a waiting part opens on the waiting panel; worked examples stay readable", async () => {
    mockApi(
      lesson({
        concept_status: "in_progress",
        progress: {
          seen_steps: ["intro", "check", "kp:kp1", "kpq:kp1"],
          last_step: "kpq:kp1",
          finished_at: null,
        },
        check_result: ANSWERED_CHECK,
        kps: [
          kp("kp1", "Along a road", "Example one.", { status: "failed", open: false }),
          kp("kp2", "Around a corner", "Example two."),
        ],
        waiting: { kp: "kp1", reopen_at: "2026-11-05T18:30:00Z", remediations: [] },
      }),
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByText("This part reopens later")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Lesson steps" });
    expect(within(nav).getByRole("button", { name: "Worked example 1" })).toBeEnabled();
    expect(within(nav).getByRole("button", { name: "Worked example 2" })).toBeDisabled();
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
    expect(await screen.findByRole("heading", { name: "Learn these first" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Linear equations/ })).toHaveAttribute(
      "href",
      `/learn/${COURSE}/maths-9-10/lin`,
    );
  });
});

describe("LessonPage · Practice step (spec 006)", () => {
  beforeEach(() => {
    progressCalls.length = 0;
    python.run.mockReset();
  });

  const withPractice = (overrides: Partial<Lesson> = {}) =>
    lesson({
      kps: [kp("kp1", "Along a road", "Example one.")],
      steps: ["intro", "check", "kp:kp1", "kpq:kp1", "practice"],
      concept_status: "in_progress",
      check_result: ANSWERED_CHECK,
      practice: { status: "pending", active: false },
      ...overrides,
    });

  const multistep: Question = {
    ...question(1),
    item_id: "ms",
    type: "multistep",
    prompt_md: "A round trip.",
    unit: null,
    steps: [
      { prompt_md: "Time out?", type: "numeric", unit: null, options: null, variables: null },
      { prompt_md: "Time back?", type: "numeric", unit: null, options: null, variables: null },
    ],
    step: 0,
    step_results: [],
  };

  function stepResult(step: number, correct: boolean, done: Partial<AnswerResult> = {}) {
    const steps = [
      { correct: true, display_answer: "1.25", note: null, misconception: null },
      { correct, display_answer: "2.00", note: null, misconception: null },
    ].slice(0, step + 1);
    return answer({ step, step_results: steps, item_done: step === 1, results: [], ...done });
  }

  it("Practice stays locked until every part passes; Next then moves to it", async () => {
    const user = userEvent.setup();
    let practiceGets = 0;
    mockApi(
      withPractice({
        progress: {
          seen_steps: ["intro", "check", "kp:kp1"],
          last_step: "kp:kp1",
          finished_at: null,
        },
      }),
      {
        [`GET ${Q_URL}`]: () => jsonResponse(200, question(1, [true])),
        [`POST ${A_URL}`]: () =>
          jsonResponse(200, answer({ results: [true, true], session_status: "passed" })),
        [`GET ${PQ_URL}`]: () => {
          practiceGets += 1;
          return jsonResponse(200, multistep);
        },
      },
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    const nav = await screen.findByRole("navigation", { name: "Lesson steps" });
    expect(within(nav).getByRole("button", { name: "Practice" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(await screen.findByLabelText("Your answer"), "8");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await user.click(await screen.findByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Practice · Put it together")).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 2")).toBeInTheDocument();
    expect(practiceGets).toBe(1);
    // "Finish lesson" is replaced by passing Practice.
    expect(screen.queryByRole("button", { name: "Finish lesson" })).not.toBeInTheDocument();
  });

  it("passing Practice shows the learned screen", async () => {
    const user = userEvent.setup();
    const bodies: Record<string, unknown>[] = [];
    mockApi(
      withPractice({ kps: [kp("kp1", "Along a road", "Example one.", { status: "passed" })] }),
      {
        [`GET ${PQ_URL}`]: () => jsonResponse(200, multistep),
        [`POST ${PA_URL}`]: (init) => {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          bodies.push(body);
          return jsonResponse(
            200,
            body.step === 0
              ? stepResult(0, true)
              : stepResult(1, true, {
                  session_status: "passed",
                  item_correct: true,
                  results: [true],
                  concept_learned: true,
                  unlocked: [{ id: `${COURSE}/speed-and-velocity`, title: "Speed and velocity" }],
                }),
          );
        },
      },
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    expect(await screen.findByText("Step 1 of 2")).toBeInTheDocument(); // resumes at Practice
    await user.type(screen.getByLabelText("Your answer"), "1.25");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Step 2 of 2")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your answer"), "2");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Practice passed ✓")).toBeInTheDocument();
    expect(screen.getByText("Problem solved ✓")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Concept learned ✓")).toBeInTheDocument();
    expect(bodies.map((b) => b.step)).toEqual([0, 1]);
    // Answers name the session they were shown in (a stale tab can't answer a new attempt).
    expect(bodies.map((b) => b.session_id)).toEqual(["sess1", "sess1"]);
    await waitFor(() =>
      expect(progressCalls).toContainEqual({ step: "practice", active_seconds: 0 }),
    );
  });

  it("a failed code task keeps the student's code for the next try", async () => {
    const user = userEvent.setup();
    const code: Question = {
      ...question(1),
      item_id: "code",
      type: "code",
      prompt_md: "Write `double(n)`.",
      unit: null,
      code: {
        entry: "double",
        starter: "def double(n):\n    pass\n",
        prefill: null,
        time_limit_ms: 2000,
        tests: [
          {
            visible: true,
            returns: "value",
            args: "[2]",
            stdin: null,
            expected: "4",
            expected_stdout: null,
          },
        ],
      },
    };
    let gets = 0;
    let submittedCode = "";
    python.run.mockResolvedValue({ outputs: [{ json: "5" }], passed: [false] });
    mockApi(
      withPractice({ kps: [kp("kp1", "Along a road", "Example one.", { status: "passed" })] }),
      {
        [`GET ${PQ_URL}`]: () => {
          gets += 1;
          return jsonResponse(
            200,
            gets === 1
              ? code
              : { ...code, session_id: "sess2", code: { ...code.code!, prefill: submittedCode } },
          );
        },
        [`POST ${PA_URL}`]: (init) => {
          submittedCode = (JSON.parse(String(init.body)) as { code: string }).code;
          return jsonResponse(
            200,
            answer({
              correct: false,
              session_status: "failed",
              results: [false],
              tests: [
                {
                  visible: true,
                  passed: false,
                  status: "failed",
                  args: "[2]",
                  stdin: null,
                  expected: "4",
                  got: "5",
                },
              ],
              solution: null,
            }),
          );
        },
      },
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    const editor = await screen.findByLabelText("Code editor");
    await user.type(editor, "# try 1");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Not quite: 0 of 1 tests passed")).toBeInTheDocument();
    expect(screen.queryByTestId("solution")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Fix your code and submit again" }));
    await waitFor(() => expect(gets).toBe(2));
    expect(await screen.findByLabelText("Code editor")).toHaveValue(submittedCode);
    expect(submittedCode).toContain("# try 1");
  });

  it("a learned concept shows Passed and offers an unscored Practise again", async () => {
    const user = userEvent.setup();
    const urls: string[] = [];
    mockApi(
      withPractice({
        concept_status: "learned",
        kps: [kp("kp1", "Along a road", "Example one.", { status: "passed" })],
        practice: { status: "passed", active: false },
      }),
      {
        [`GET ${PQ_URL}`]: () =>
          jsonResponse(200, { ...multistep, session_id: null, preview_seed: 7 }),
      },
    );
    const realFetch = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        urls.push(String(input));
        return realFetch(input, init);
      }),
    );
    renderAt(`/learn/${COURSE}/${DIST}`);
    const nav = await screen.findByRole("navigation", { name: "Lesson steps" });
    await user.click(within(nav).getByRole("button", { name: "Practice (passed)" }));
    expect(await screen.findByText("Passed ✓")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Practise again" }));
    expect(await screen.findByText("Step 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Practice only, no XP")).toBeInTheDocument();
    expect(urls.some((u) => u.endsWith("/practice/question?again=true"))).toBe(true);
  });
});

describe("CoursePage", () => {
  it("shows statuses and opens the locked sheet with unfinished prereqs", async () => {
    const user = userEvent.setup();
    mockApi(lesson());
    renderAt(`/learn/${COURSE}`);
    expect(await screen.findByRole("heading", { name: "Physics" })).toBeInTheDocument();
    expect(screen.getByText("1 of 3 concepts learned")).toBeInTheDocument();
    expect(screen.getByText("Class 9")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Distance and displacement/ })).toHaveAttribute(
      "href",
      `/learn/${COURSE}/${DIST}`,
    );

    await user.click(screen.getByRole("button", { name: /Speed and velocity/ }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText("Learn these first")).toBeInTheDocument();
    // Only the unfinished prerequisite is listed, linking to its lesson.
    expect(
      within(sheet).getByRole("link", { name: /Linear equations in two variables/ }),
    ).toBeInTheDocument();
    expect(within(sheet).queryByText("Distance and displacement")).toBeNull();
  });

  it("defaults to the list on phones and lazy-loads the map when chosen (remembered)", async () => {
    const user = userEvent.setup();
    window.localStorage.removeItem("learn.courseView");
    mockApi(lesson());
    renderAt(`/learn/${COURSE}`);
    expect(await screen.findByRole("heading", { name: "Physics" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Map view stub")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Map" }));
    expect(await screen.findByText("Map view stub")).toBeInTheDocument();
    expect(window.localStorage.getItem("learn.courseView")).toBe("map");
  });

  it("defaults to the map on wide screens", async () => {
    window.localStorage.removeItem("learn.courseView");
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("768"),
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    mockApi(lesson());
    renderAt(`/learn/${COURSE}`);
    expect(await screen.findByText("Map view stub")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Map" })).toHaveAttribute("aria-pressed", "true");
  });
});
