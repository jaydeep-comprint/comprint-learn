import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ExpressionInput } from "@/features/learn/ExpressionInput";
import { NumericInput } from "@/features/learn/NumericInput";
import { toTex } from "@/features/learn/toTex";

describe("NumericInput", () => {
  it("brings up the decimal keyboard and shows the unit as a suffix", () => {
    render(<NumericInput id="n" value="" unit="m/s" onChange={() => {}} />);
    expect(screen.getByRole("textbox")).toHaveAttribute("inputmode", "decimal");
    expect(screen.getByTestId("unit-suffix")).toHaveTextContent("m/s");
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
