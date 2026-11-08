import { render, screen } from "@testing-library/react";
import { ReactFlowProvider, type NodeProps } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";

import { ConceptNode, type ConceptFlowNode, type MapConcept, type MapMode } from "./ConceptNode";

function concept(overrides: Partial<MapConcept> = {}): MapConcept {
  return {
    id: "maths/lin",
    title: "Linear equations",
    summary: "",
    status: "learned",
    prereqs: [],
    kps_passed: 3,
    kps_total: 3,
    parts_passed: 3,
    parts_total: 3,
    waiting: null,
    brush_up: false,
    brush_up_id: null,
    state: "learned",
    memory: { band: "weak" },
    ...overrides,
  };
}

function node(c: MapConcept, mode: MapMode) {
  const props = { data: { concept: c, selected: false, onSelect: vi.fn(), mode } };
  render(
    <ReactFlowProvider>
      <ConceptNode {...(props as unknown as NodeProps<ConceptFlowNode>)} />
    </ReactFlowProvider>,
  );
}

describe("ConceptNode (teacher view, spec 010)", () => {
  it("memory mode colours learned nodes by band and says so", () => {
    node(concept(), "memory");
    const button = screen.getByRole("button", { name: /Linear equations, Learned, memory weak/ });
    expect(button).toHaveAttribute("data-band", "weak");
  });

  it("memory mode greys concepts that aren't learned", () => {
    node(concept({ status: "in_progress", state: "in_progress", memory: null }), "memory");
    const button = screen.getByRole("button", { name: /Linear equations, In progress/ });
    expect(button).not.toHaveAttribute("data-band");
    expect(button).toHaveClass("opacity-60");
  });

  it("progress mode marks stuck concepts", () => {
    node(
      concept({ status: "in_progress", state: "stuck", memory: null, parts_passed: 1 }),
      "progress",
    );
    expect(screen.getByRole("button", { name: /, stuck$/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Stuck")).toBeInTheDocument();
  });

  it("marks placed concepts, and conditional ones as check soon (spec 012)", () => {
    node(concept({ placed: true, conditional: true, memory: null }), "progress");
    expect(
      screen.getByRole("button", { name: /Linear equations, Learned, Placed · check soon/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Placed · check soon")).toBeInTheDocument();
  });

  it("shows no chip for a lesson-learned concept", () => {
    node(concept({ memory: null }), "progress");
    expect(screen.queryByText(/Placed/)).not.toBeInTheDocument();
  });
});
