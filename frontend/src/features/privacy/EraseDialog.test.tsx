import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  getAccessToken: async () => "token",
  signOut: async () => {},
}));
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast: toasts }));

import { renderAt } from "@/features/xp/testUtils";
import { attachmentName } from "@/lib/api";
import { jsonResponse, routeFetch } from "@/test/render";

import { EraseDialog } from "./EraseDialog";

const target = { id: "s1", display_name: "Asha", username: "asha42" };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EraseDialog", () => {
  it("enables Erase only when the username matches, then schedules it", async () => {
    const bodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "POST /api/v1/students/s1/erasure": (init) => {
            bodies.push(JSON.parse(String(init.body)));
            return jsonResponse(200, {});
          },
        }),
      ),
    );
    const onClose = vi.fn();
    renderAt(<EraseDialog student={target} onClose={onClose} />);
    const button = screen.getByRole("button", { name: "Erase student" });
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "Their learning records stay without a name",
    );
    expect(button).toBeDisabled();
    const input = screen.getByLabelText(/to confirm/);
    await userEvent.type(input, "asha4");
    expect(button).toBeDisabled();
    await userEvent.type(input, "2");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(bodies).toEqual([{ confirm_username: "asha42" }]);
    expect(toasts.success).toHaveBeenCalledWith("Erasure of Asha scheduled");
  });

  it("shows the server error inline and stays open", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        routeFetch({
          "POST /api/v1/students/s1/erasure": () =>
            jsonResponse(502, {
              code: "auth_service_unavailable",
              message: "Couldn't reach the sign-in service. Nothing was changed; please try again.",
            }),
        }),
      ),
    );
    const onClose = vi.fn();
    renderAt(<EraseDialog student={target} onClose={onClose} />);
    await userEvent.type(screen.getByLabelText(/to confirm/), "ASHA42");
    await userEvent.click(screen.getByRole("button", { name: "Erase student" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't reach the sign-in service",
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});

describe("attachmentName", () => {
  it("reads the export's filename", () => {
    expect(attachmentName('attachment; filename="student-asha42-2026-11-11.json"')).toBe(
      "student-asha42-2026-11-11.json",
    );
    expect(attachmentName(null)).toBeNull();
  });
});
