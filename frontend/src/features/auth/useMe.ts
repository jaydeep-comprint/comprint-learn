import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/features/auth/AuthProvider";
import { apiFetch } from "@/lib/api";
import type { Me } from "@/lib/types";

export const ME_KEY = ["me"] as const;

export function useMe() {
  const { session } = useAuth();
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => apiFetch<Me>("/api/v1/me"),
    enabled: session !== null,
    staleTime: 60_000,
    retry: false,
  });
}
