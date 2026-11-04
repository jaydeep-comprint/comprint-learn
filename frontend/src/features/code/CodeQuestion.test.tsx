import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PythonStatus, RunResult } from "@/features/code/usePython";

const python = {
  status: { state: "ready" } as PythonStatus,
  run: vi.fn<(...args: unknown[]) => Promise<RunResult>>(),
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

import { QuestionStep } from "@/features/learn/QuestionStep";
import type { AnswerResult, Question } from "@/lib/types";

const question: Question = {
  session_id: "s",
  position: 1,
  item_id: "code",
  type: "code",
  prompt_md: "Write `double(n)`.",
  unit: null,
  options: null,
  variables: null,
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
      {
        visible: false,
        returns: "value",
        args: "[3]",
        stdin: null,
        expected: null,
        expected_stdout: null,
      },
    ],
  },
  results: [],
  preview_seed: null,
};

function submitted(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    correct: false,
    display_answer: "",
    explanation_md: null,
    misconception: null,
    note: null,
    session_status: "failed",
    already_answered: false,
    results: [false],
    concept_learned: false,
    unlocked: [],
    remediations: [],
    item_done: true,
    item_correct: false,
    tests: [
      {
        visible: true,
        passed: true,
        status: "passed",
        args: "[2]",
        stdin: null,
        expected: "4",
        got: "4",
      },
      {
        visible: false,
        passed: false,
        status: "failed",
        args: "[3]",
        stdin: null,
        expected: null,
        got: "7",
      },
    ],
    solution: null,
    ...overrides,
  };
}

async function setup(props: Partial<Parameters<typeof QuestionStep>[0]> = {}) {
  const handlers = { onSubmit: vi.fn(), onNext: vi.fn(), onContinue: vi.fn() };
  render(
    <QuestionStep
      header="Practice"
      question={question}
      result={null}
      submitting={false}
      {...handlers}
      {...props}
    />,
  );
  await screen.findByLabelText("Code editor"); // the code question is lazy-loaded
  return handlers;
}

describe("CodeQuestion", () => {
  beforeEach(() => {
    python.status = { state: "ready" };
    python.run.mockReset();
  });

  it("Run runs the visible tests in the browser and never calls the API", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    python.run.mockResolvedValue({ outputs: [{ json: "5" }], passed: [false] });
    const { onSubmit } = await setup();
    await user.click(screen.getByRole("button", { name: "Run" }));
    const [code, entry, tests] = python.run.mock.calls[0] ?? [];
    expect(code).toBe(question.code?.starter);
    expect(entry).toBe("double");
    expect(tests).toHaveLength(1);
    const row = await screen.findByTestId("visible-test");
    expect(row).toHaveTextContent("double(2)");
    expect(row).toHaveTextContent("Expected4");
    expect(row).toHaveTextContent("Got5");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("Submit runs every test and sends the code and outputs", async () => {
    const user = userEvent.setup();
    python.run.mockResolvedValue({ outputs: [{ json: "4" }, { json: "7" }], passed: [true, null] });
    const { onSubmit } = await setup();
    await user.type(screen.getByLabelText("Code editor"), "# mine");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(python.run.mock.calls[0]?.[2]).toHaveLength(2);
    expect(onSubmit).toHaveBeenCalledWith({
      code: `${question.code?.starter}# mine`,
      outputs: [{ json: "4" }, { json: "7" }],
    });
  });

  it("never shows an expected value for hidden tests", async () => {
    await setup({ result: submitted() });
    const hidden = screen.getByTestId("hidden-test");
    expect(hidden).toHaveTextContent("Hidden test 1");
    expect(hidden).toHaveTextContent("double(3)");
    expect(hidden).not.toHaveTextContent("Expected");
    expect(hidden).toHaveTextContent("Your result differs from the expected one.");
    expect(screen.getByText("Not quite: 1 of 2 tests passed")).toBeInTheDocument();
    expect(screen.queryByTestId("solution")).not.toBeInTheDocument();
  });

  it("shows the solution when it's sent", async () => {
    await setup({
      result: submitted({ correct: true, solution: "def double(n):\n    return 2 * n\n" }),
    });
    expect(screen.getByTestId("solution")).toHaveTextContent("return 2 * n");
  });

  it("shows a timeout on that test", async () => {
    const user = userEvent.setup();
    python.run.mockResolvedValue({ outputs: [{ timeout: true }], passed: [null] });
    await setup();
    await user.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByText("Took too long (over 2 s)")).toBeInTheDocument();
    expect(screen.getByLabelText("Code editor")).toBeEnabled();
  });

  it("disables Run and Submit while Python loads, and offers Retry when it fails", async () => {
    const user = userEvent.setup();
    python.status = { state: "loading", stage: "runtime" };
    const { rerender } = render(
      <QuestionStep
        header="P"
        question={question}
        result={null}
        submitting={false}
        onSubmit={vi.fn()}
        onNext={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    expect(await screen.findByText(/Loading Python/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "60");
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    python.status = { state: "error", message: "offline" };
    rerender(
      <QuestionStep
        header="P"
        question={{ ...question }}
        result={null}
        submitting={false}
        onSubmit={vi.fn()}
        onNext={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    expect(screen.getByText("Couldn't load Python. Check your connection.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(python.retry).toHaveBeenCalled();
  });

  it("starts from the last submitted code when there is one", async () => {
    await setup({
      question: {
        ...question,
        code: { ...question.code!, prefill: "def double(n):\n    return n\n" },
      },
    });
    expect(screen.getByLabelText("Code editor")).toHaveValue("def double(n):\n    return n\n");
  });
});
