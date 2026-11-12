import { afterEach, describe, expect, it, vi } from "vitest";

const sonner = vi.hoisted(() => ({ toast: { error: vi.fn() } }));
vi.mock("sonner", () => sonner);

import { ApiError } from "@/lib/api";
import { createQueryClient } from "@/lib/queryClient";

describe("createQueryClient (spec 015)", () => {
  afterEach(() => sonner.toast.error.mockClear());

  it("does not retry a 429 and toasts the rate-limit message once", async () => {
    const client = createQueryClient();
    const fn = vi.fn().mockRejectedValue(new ApiError(429, "/x", "rate_limited"));
    await expect(client.fetchQuery({ queryKey: ["a"], queryFn: fn })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(fn).toHaveBeenCalledTimes(1);
    expect(sonner.toast.error).toHaveBeenCalledWith(
      "Too many requests. Wait a moment and try again.",
      { id: "rate-limited" },
    );
  });

  it("does not toast other errors globally", async () => {
    const client = createQueryClient();
    const fn = vi.fn().mockRejectedValue(new ApiError(404, "/x", "not_found"));
    await client.fetchQuery({ queryKey: ["b"], queryFn: fn }).catch(() => {});
    expect(sonner.toast.error).not.toHaveBeenCalled();
  });

  it("leaves a 429 toast to mutations that handle their own errors", async () => {
    const client = createQueryClient();
    const error = new ApiError(429, "/x", "rate_limited");
    const own = client.getMutationCache().build(client, {
      mutationFn: () => Promise.reject(error),
      onError: () => {},
    });
    await own.execute(undefined).catch(() => {});
    expect(sonner.toast.error).not.toHaveBeenCalled();
    const bare = client.getMutationCache().build(client, {
      mutationFn: () => Promise.reject(error),
    });
    await bare.execute(undefined).catch(() => {});
    expect(sonner.toast.error).toHaveBeenCalledTimes(1);
  });
});
