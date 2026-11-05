import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { AtRiskRow, Heatmap as HeatmapData, MisconceptionStat } from "@/lib/types";

import { useWindow } from "./api";
import { AtRiskList } from "./AtRiskList";
import { Heatmap } from "./Heatmap";
import { MisconceptionList } from "./MisconceptionList";
import { WindowPicker } from "./WindowPicker";

function at(element: React.ReactNode, path = "/") {
  const router = createMemoryRouter([{ path: "/", element }], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

const heat: HeatmapData = {
  chapters: [
    {
      title: "Linear equations",
      grade: 9,
      concepts: [
        { concept: "maths/lin", title: "Linear equations", learned_pct: 50 },
        { concept: "maths/graph", title: "Graphs", learned_pct: 0 },
      ],
    },
    {
      title: "Quadratics",
      grade: 10,
      concepts: [{ concept: "maths/quad", title: "Quadratics", learned_pct: 0 }],
    },
  ],
  students: [
    {
      student_id: "s1",
      display_name: "Asha",
      cells: [
        { state: "learned", band: "fading" },
        { state: "stuck", band: null },
        { state: "locked", band: null },
      ],
    },
    {
      student_id: "s2",
      display_name: "Ravi",
      cells: [
        { state: "in_progress", band: null },
        { state: "ready", band: null },
        { state: "locked", band: null },
      ],
    },
  ],
};

describe("Heatmap", () => {
  it("labels every cell, links names and shows a legend", () => {
    const open = vi.fn();
    at(<Heatmap classId="c1" data={heat} grade={9} onOpenConcept={open} />);
    expect(
      screen.getByRole("button", { name: "Asha · Linear equations · Learned, memory fading" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Asha · Graphs · Stuck" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ravi · Graphs · Ready" })).toBeInTheDocument();
    const name = screen.getByRole("link", { name: "Asha" });
    expect(name).toHaveAttribute("href", "/classes/c1/students/s1");
    expect(name.closest("th")).toHaveClass("sticky");
    expect(screen.getByText("Learned, memory weak")).toBeInTheDocument();
    // Defaults to the class's grade: the Class 10 chapter is hidden until "All chapters".
    expect(screen.queryByRole("button", { name: /Quadratics ·/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "All chapters" }));
    expect(screen.getByRole("button", { name: "Asha · Quadratics · Locked" })).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Graphs"));
    expect(open).toHaveBeenCalledWith("maths/graph");
  });

  it("shows an empty state without students", () => {
    at(<Heatmap classId="c1" data={{ ...heat, students: [] }} grade={9} onOpenConcept={vi.fn()} />);
    expect(screen.getByText("No students yet.")).toBeInTheDocument();
  });
});

function Picker() {
  const [w, setW] = useWindow();
  return <WindowPicker value={w} onChange={setW} />;
}

describe("WindowPicker", () => {
  it("keeps the window in the URL", () => {
    const router = at(<Picker />, "/?window=30d");
    expect(screen.getByRole("button", { name: "30 d" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(router.state.location.search).toBe("?window=all");
    fireEvent.click(screen.getByRole("button", { name: "7 d" }));
    expect(router.state.location.search).toBe("");
  });
});

describe("AtRiskList", () => {
  it("lists reasons as chips and links to the student", () => {
    const rows: AtRiskRow[] = [
      {
        student_id: "s1",
        display_name: "Asha",
        reasons: [
          { code: "kp_fail_rate", detail: "Failed 3 of 12 KP tries" },
          { code: "negative_xp", detail: "Lost XP for rushing (2×)" },
        ],
      },
    ];
    at(<AtRiskList classId="c1" rows={rows} />);
    expect(screen.getByRole("link", { name: "Asha" })).toHaveAttribute(
      "href",
      "/classes/c1/students/s1",
    );
    expect(screen.getByText("Failed 3 of 12 KP tries")).toBeInTheDocument();
    expect(screen.getByText("Lost XP for rushing (2×)")).toBeInTheDocument();
  });

  it("celebrates an empty list", () => {
    at(<AtRiskList classId="c1" rows={[]} />);
    expect(screen.getByText(/No one is at risk this week/)).toBeInTheDocument();
  });
});

describe("MisconceptionList", () => {
  const rows: MisconceptionStat[] = [
    {
      id: "m1",
      title: "Velocity is the same as speed",
      concept: "physics/speed",
      concept_title: "Speed and velocity",
      chosen: 6,
      offered: 15,
      rate: 0.4,
      students: 6,
      items: [
        {
          prompt: "Is the velocity constant?",
          chosen_text: "Yes",
          student_names: ["Asha", "Ravi"],
        },
      ],
    },
  ];

  it("expands to the chosen distractor and names, and prefills Assign", () => {
    const assign = vi.fn();
    at(<MisconceptionList rows={rows} onAssign={assign} />);
    expect(screen.getByText("chosen in 40% of answers (6 students)")).toBeInTheDocument();
    expect(screen.queryByText("Asha, Ravi")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    const item = screen.getByText("Is the velocity constant?").closest("li")!;
    expect(within(item).getByText("Yes")).toBeInTheDocument();
    expect(within(item).getByText("Asha, Ravi")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    expect(assign).toHaveBeenCalledWith("physics/speed");
  });

  it("has an empty state", () => {
    at(<MisconceptionList rows={[]} />);
    expect(screen.getByText("No misconceptions picked up yet.")).toBeInTheDocument();
  });
});
