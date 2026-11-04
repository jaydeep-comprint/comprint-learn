import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ExpressionInput } from "@/features/learn/ExpressionInput";
import { NumericInput } from "@/features/learn/NumericInput";
import { toTex } from "@/features/learn/toTex";

function WithUnit() {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  return (
    <NumericInput
      id="n"
      value={value}
      unit="m/s"
      unitRequired
      unitValue={unit}
      onChange={setValue}
      onUnitChange={setUnit}
    />
  );
}

describe("NumericInput", () => {
  it("has a unit box with a live preview when the answer has a unit", async () => {
    const user = userEvent.setup();
    render(<WithUnit />);
    expect(screen.getByRole("textbox", { name: "" })).toHaveAttribute("inputmode", "decimal");
    const unit = screen.getByRole("textbox", { name: "Unit" });
    expect(unit).toHaveAttribute("placeholder", "unit, e.g. m/s");
    expect(unit).toHaveAttribute("inputmode", "text");
    expect(screen.queryByTestId("unit-suffix")).not.toBeInTheDocument();
    await user.type(unit, "km/hr");
    expect(screen.getByText("Read as: km·h⁻¹")).toBeInTheDocument();
    await user.clear(unit);
    await user.type(unit, "furlongs");
    expect(screen.getByText("Not a unit we know")).toBeInTheDocument();
  });

  it("has the number box only when the answer is unitless", () => {
    render(<NumericInput id="n" value="" unit={null} onChange={() => {}} />);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByRole("textbox")).toHaveAttribute("inputmode", "decimal");
    expect(screen.queryByRole("textbox", { name: "Unit" })).not.toBeInTheDocument();
  });
});

function Controlled() {
  const [value, setValue] = useState("");
  return <ExpressionInput id="e" value={value} variables={["x"]} onChange={setValue} />;
}

describe("ExpressionInput", () => {
  it("previews what is typed with KaTeX and shows the hint", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    expect(screen.getByText(/Use \^ for powers, e\.g\. 3x\^2 \+ 2/)).toBeInTheDocument();
    expect(screen.getByTestId("expression-preview").innerHTML).toBe("");
    await user.type(screen.getByRole("textbox"), "3x^2 + 2");
    expect(screen.getByTestId("expression-preview").querySelector(".katex")).not.toBeNull();
  });

  it("converts powers, roots and products for the preview", () => {
    expect(toTex("x^10")).toBe("x^{10}");
    expect(toTex("x^(n+1)")).toBe("x^{n+1}");
    expect(toTex("sqrt(x)")).toBe("\\sqrt{x}");
    expect(toTex("2*x")).toBe("2 \\cdot x");
  });
});
