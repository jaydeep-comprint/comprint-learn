import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CheckStep } from "@/features/learn/CheckStep";
import type { CheckResult } from "@/lib/types";

const check = {
  item_id: "i1",
  prompt: "Which has a direction?",
  options: [
    { id: "b", text: "Distance" },
    { id: "a", text: "Displacement" },
  ],
};

const wrong: CheckResult = {
  correct: false,
  chosen: "b",
  correct_option: "a",
  explanation_md: "Displacement is a vector.",
  misconception: { title: "Displacement is the same as distance" },
};

describe("CheckStep", () => {
  it("enables Submit only after a pick", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <CheckStep check={check} result={null} assetBase="" submitting={false} onSubmit={onSubmit} />,
    );
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "Distance" }));
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledWith("b");
  });

  it("shows a wrong answer with the mix-up and the explanation", () => {
    render(
      <CheckStep check={check} result={wrong} assetBase="" submitting={false} onSubmit={vi.fn()} />,
    );
    expect(screen.getByText("Not quite")).toBeInTheDocument();
    expect(
      screen.getByText("Common mix-up: Displacement is the same as distance"),
    ).toBeInTheDocument();
    expect(screen.getByText("Displacement is a vector.")).toBeInTheDocument();
    expect(screen.getByText("Correct answer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
  });

  it("shows a correct answer without a mix-up", () => {
    render(
      <CheckStep
        check={check}
        result={{ ...wrong, correct: true, chosen: "a", misconception: null }}
        assetBase=""
        submitting={false}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("Correct!")).toBeInTheDocument();
    expect(screen.queryByText(/Common mix-up/)).toBeNull();
    expect(screen.getByRole("radio", { name: /Displacement/ })).toBeChecked();
  });

  it("moves focus to the result after a submit", () => {
    const { rerender } = render(
      <CheckStep check={check} result={null} assetBase="" submitting={false} onSubmit={vi.fn()} />,
    );
    rerender(
      <CheckStep check={check} result={wrong} assetBase="" submitting={false} onSubmit={vi.fn()} />,
    );
    expect(screen.getByRole("status")).toHaveFocus();
  });
});
