import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QuizTimer } from "@/features/quiz/QuizTimer";

describe("QuizTimer", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts down, warns under a minute and expires once", () => {
    const onExpire = vi.fn();
    render(<QuizTimer secondsLeft={62} onExpire={onExpire} />);
    const timer = screen.getByRole("timer");
    expect(timer).toHaveTextContent("1:02");
    expect(timer).not.toHaveAttribute("data-warning");
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(timer).toHaveTextContent("0:59");
    expect(timer).toHaveAttribute("data-warning", "true");
    expect(onExpire).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(timer).toHaveTextContent("0:00");
    expect(onExpire).toHaveBeenCalledTimes(1);
  });
});
