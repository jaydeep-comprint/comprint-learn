import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, retryUnlessClientError } from "@/lib/api";
import { RATE_LIMITED_MESSAGE } from "@/lib/errors";

const RATE_LIMIT_TOAST_ID = "rate-limited";

function toastIfRateLimited(error: unknown): void {
  if (error instanceof ApiError && error.status === 429) {
    // One toast however many queries hit the limit at once.
    toast.error(RATE_LIMITED_MESSAGE, { id: RATE_LIMIT_TOAST_ID });
  }
}

/**
 * The app's QueryClient (spec 015): no 4xx is retried anywhere (so a 429 is never retried), and a
 * 429 shows the rate-limit toast. Mutations with their own `onError` toast it themselves (via
 * `errorMessage`), so the global toast is only for those without one.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({ onError: toastIfRateLimited }),
    mutationCache: new MutationCache({
      onError: (error, _vars, _ctx, mutation) => {
        if (!mutation.options.onError) toastIfRateLimited(error);
      },
    }),
    defaultOptions: {
      queries: { refetchOnWindowFocus: false, retry: retryUnlessClientError },
      mutations: { retry: false },
    },
  });
}
