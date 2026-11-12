import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));

import { TUTOR_CONSENT_NOTE, TutorButton } from "@/features/tutor/TutorButton";
import { TutorPanel } from "@/features/tutor/TutorPanel";
import { renderAt } from "@/features/xp/testUtils";
import type { TutorMessage, TutorThread } from "@/lib/types";
import { jsonResponse, routeFetch } from "@/test/render";

const BASE = "/api/v1/tutor/s1/2";

function thread(overrides: Partial<TutorThread> = {}): TutorThread {
  return {
    enabled: true,
    consent: true,
    mode: "before",
    closed: false,
    hints_used: 0,
    hints_left: 3,
    next_rung: 1,
    chat_left: 10,
    daily_left: 20,
    resets_at: "2026-11-05T18:30:00Z",
    messages: [],
    ...overrides,
  };
}

function msg(overrides: Partial<TutorMessage>): TutorMessage {
  return {
    id: crypto.randomUUID(),
    role: "tutor",
    kind: "hint",
    rung: 1,
    text: "Look at the worked example.",
    link: null,
    created_at: "2026-11-05T10:00:00Z",
    ...overrides,
  };
}

function draftRef(value: string | null = null) {
  const ref = createRef<string | null>() as { current: string | null };
  ref.current = value;
  return ref;
}

function renderPanel(draft = draftRef()) {
  return renderAt(<TutorPanel open onClose={() => {}} sessionId="s1" position={2} draft={draft} />);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TutorPanel", () => {
  it("shows the empty state, the privacy line and the hint cost", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(routeFetch({ [`GET ${BASE}`]: () => jsonResponse(200, thread()) })),
    );
    renderPanel();
    expect(await screen.findByText(/Stuck\? A hint points you/)).toBeInTheDocument();
    expect(screen.getByText(/Your teacher can read this chat/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Hint 1 of 3 · lowers this session's XP by 25%/ }),
    ).toBeEnabled();
    expect(screen.getByPlaceholderText("Ask what a word or symbol means…")).toBeInTheDocument();
    expect(screen.getByText("20 tutor messages left today")).toBeInTheDocument();
  });

  it("asks for a hint with the draft and shows the labelled reply and prerequisite link", async () => {
    const fetchMock = vi.fn(
      routeFetch({
        [`GET ${BASE}`]: () =>
          jsonResponse(200, thread({ hints_used: 1, hints_left: 2, next_rung: 2 })),
        [`POST ${BASE}/hint`]: () => {
          const reply = msg({
            rung: 2,
            text: "This uses $v = d/t$ ideas from distance.",
            link: {
              id: "physics-9-10/distance-and-displacement",
              title: "Distance and displacement",
            },
          });
          return jsonResponse(200, {
            message: reply,
            thread: thread({
              hints_used: 2,
              hints_left: 1,
              next_rung: 3,
              daily_left: 19,
              messages: [msg({ role: "student", text: null, rung: 2 }), reply],
            }),
          });
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPanel(draftRef("12 m"));
    await userEvent.click(await screen.findByRole("button", { name: /Hint 2 of 3/ }));

    expect(await screen.findByText("Hint 2 · Prerequisite")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Open Distance and displacement/ });
    expect(link).toHaveAttribute(
      "href",
      "/learn/physics-9-10/physics-9-10/distance-and-displacement",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("button", { name: /Hint 3 of 3/ })).toBeInTheDocument();
    expect(screen.getByText("19 tutor messages left today")).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/hint"))!;
    expect(JSON.parse(String(init?.body))).toEqual({ draft: "12 m" });
  });

  it("disables the hint button after 3 hints", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          [`GET ${BASE}`]: () =>
            jsonResponse(200, thread({ hints_used: 3, hints_left: 0, next_rung: null })),
        }),
      ),
    );
    renderPanel();
    expect(await screen.findByRole("button", { name: "No hints left" })).toBeDisabled();
  });

  it("shows the daily cap message on 429", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          [`GET ${BASE}`]: () => jsonResponse(200, thread()),
          [`POST ${BASE}/messages`]: () =>
            jsonResponse(429, { code: "tutor_daily_cap", message: "cap", resets_at: "x" }),
        }),
      ),
    );
    renderPanel();
    await userEvent.type(await screen.findByRole("textbox"), "what is east?{Enter}");
    expect(
      await screen.findByText("You've used today's 20 tutor messages. They come back at midnight."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Hint 1 of 3/ })).toBeDisabled();
  });

  it("shows a retry on 503 and retries the same request", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          [`GET ${BASE}`]: () => jsonResponse(200, thread()),
          [`POST ${BASE}/hint`]: () => {
            calls += 1;
            if (calls === 1) return jsonResponse(503, { code: "tutor_unavailable", message: "x" });
            const reply = msg({});
            return jsonResponse(200, {
              message: reply,
              thread: thread({ hints_used: 1, hints_left: 2, next_rung: 2, messages: [reply] }),
            });
          },
        }),
      ),
    );
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: /Hint 1 of 3/ }));
    expect(
      await screen.findByText("The tutor isn't available right now. Try again in a minute."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Hint 1 · Worked example")).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it("after mode: no hint button, free chat header, explain placeholder", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          [`GET ${BASE}`]: () =>
            jsonResponse(200, thread({ mode: "after", hints_left: 0, next_rung: null })),
        }),
      ),
    );
    renderPanel();
    expect(await screen.findByText("No XP cost")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Hint/ })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask why your answer was wrong…")).toBeInTheDocument();
  });

  it("a finished question disables the chat", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(routeFetch({ [`GET ${BASE}`]: () => jsonResponse(200, thread({ closed: true })) })),
    );
    renderPanel();
    expect(await screen.findByText("This question has finished.")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("shows the counter after 400 characters", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(routeFetch({ [`GET ${BASE}`]: () => jsonResponse(200, thread()) })),
    );
    renderPanel();
    const box = await screen.findByRole("textbox");
    await userEvent.click(box);
    await userEvent.paste("a".repeat(401));
    await waitFor(() => expect(screen.getByText("401/500")).toBeInTheDocument());
  });
});

describe("TutorButton", () => {
  it("shows the hints left", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(routeFetch({ [`GET ${BASE}`]: () => jsonResponse(200, thread()) })),
    );
    renderAt(<TutorButton sessionId="s1" position={2} onOpen={() => {}} />);
    expect(
      await screen.findByRole("button", { name: "Get help · 3 hints left" }),
    ).toBeInTheDocument();
  });

  it("is hidden when the tutor is off", async () => {
    const fetchMock = vi.fn(
      routeFetch({ [`GET ${BASE}`]: () => jsonResponse(200, thread({ enabled: false })) }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderAt(<TutorButton sessionId="s1" position={2} onOpen={() => {}} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("is disabled with the lock note when no consent form is recorded (spec 014)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(routeFetch({ [`GET ${BASE}`]: () => jsonResponse(200, thread({ consent: false })) })),
    );
    renderAt(<TutorButton sessionId="s1" position={2} onOpen={() => {}} />);
    expect(await screen.findByRole("button", { name: "Get help" })).toBeDisabled();
    expect(screen.getByText(TUTOR_CONSENT_NOTE)).toBeInTheDocument();
  });
});

describe("TutorPanel consent (spec 014)", () => {
  it("closes and shows the lock when consent is withdrawn mid-session", async () => {
    let consent = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          [`GET ${BASE}`]: () => jsonResponse(200, thread({ consent })),
          [`POST ${BASE}/hint`]: () => {
            consent = false;
            return jsonResponse(403, {
              code: "tutor_consent_required",
              message: TUTOR_CONSENT_NOTE,
            });
          },
        }),
      ),
    );
    const onClose = vi.fn();
    renderAt(
      <>
        <TutorButton sessionId="s1" position={2} onOpen={() => {}} />
        <TutorPanel open onClose={onClose} sessionId="s1" position={2} draft={draftRef()} />
      </>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Hint 1 of 3/ }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Get help" })).toBeDisabled();
    expect(screen.getAllByText(TUTOR_CONSENT_NOTE).length).toBeGreaterThan(0);
  });
});
