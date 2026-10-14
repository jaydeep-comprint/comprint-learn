import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { slipsStore } from "@/features/slips/store";
import type { SchoolClass } from "@/lib/types";
import { createFakeSupabase, fakeSession } from "@/test/fakeSupabase";
import { jsonResponse, renderRoutes, routeFetch } from "@/test/render";

const fake = vi.hoisted(() => ({ current: null as ReturnType<typeof createFakeSupabase> | null }));
vi.mock("@/lib/supabase", () => ({
  getSupabase: () => fake.current!.client,
  getAccessToken: async () => "token-123",
  signOut: async () => {},
}));

import { CreateStudentsForm } from "@/features/classes/AddStudentsDialog";

const cls: SchoolClass = {
  id: "c1",
  name: "9A Maths",
  subject: "maths",
  grade: 9,
  archived: false,
  student_count: 0,
  teachers: [],
};

function renderForm(onDone = vi.fn()) {
  return renderRoutes(
    [
      { path: "/classes/c1", element: <CreateStudentsForm cls={cls} onDone={onDone} /> },
      { path: "/classes/c1/slips", element: <p>Slips page</p> },
    ],
    "/classes/c1",
  );
}

describe("Create new students", () => {
  beforeEach(() => {
    fake.current = createFakeSupabase();
    fake.current.state.session = fakeSession();
    slipsStore.clear();
  });

  it("counts non-blank lines live", async () => {
    const user = userEvent.setup();
    renderForm();
    expect(screen.getByText("0 names · max 60")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create students" })).toBeDisabled();
    await user.type(screen.getByLabelText("One name per line"), "Aarav S.{Enter}{Enter}  Priya K.");
    expect(screen.getByText("2 names · max 60")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create 2 students" })).toBeEnabled();
  });

  it("blocks more than 60 names", async () => {
    const user = userEvent.setup();
    renderForm();
    const names = Array.from({ length: 61 }, (_, i) => `Student ${i}`).join("\n");
    await user.click(screen.getByLabelText("One name per line"));
    await user.paste(names);
    expect(screen.getByText("That's 61 names. Add at most 60 at a time.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create 61 students" })).toBeDisabled();
  });

  it("creates students and opens the slips view with their temp passwords", async () => {
    const created = [
      { id: "s1", display_name: "Aarav S.", username: "aarav42", temp_password: "tiger-maple-42" },
      { id: "s2", display_name: "Priya K.", username: "priya17", temp_password: "otter-lake-07" },
    ];
    const fetchMock = vi.fn(
      routeFetch({ "POST /api/v1/classes/c1/students": () => jsonResponse(201, created) }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onDone = vi.fn();
    const user = userEvent.setup();
    renderForm(onDone);
    await user.type(screen.getByLabelText("One name per line"), "Aarav S.{Enter}Priya K.");
    await user.click(screen.getByRole("button", { name: "Create 2 students" }));

    expect(await screen.findByText("Slips page")).toBeInTheDocument();
    expect(onDone).toHaveBeenCalled();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ display_names: ["Aarav S.", "Priya K."] });
    expect(slipsStore.get()?.slips).toEqual(created);
  });

  it("shows the all-or-nothing error and stays put", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "POST /api/v1/classes/c1/students": () =>
            jsonResponse(502, {
              code: "accounts_not_created",
              message: "Could not create accounts right now. Nothing was saved; please try again.",
            }),
        }),
      ),
    );
    const user = userEvent.setup();
    renderForm();
    await user.type(screen.getByLabelText("One name per line"), "Aarav");
    await user.click(screen.getByRole("button", { name: "Create 1 student" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Could not create accounts right now. Nothing was saved; please try again.",
      ),
    );
    expect(slipsStore.get()).toBeNull();
  });
});
