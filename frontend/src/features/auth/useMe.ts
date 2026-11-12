import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { useAuth } from "@/features/auth/AuthProvider";
import { apiFetch } from "@/lib/api";
import { setObservedUser } from "@/lib/observability";
import type { Me } from "@/lib/types";

export const ME_KEY = ["me"] as const;

export function useMe() {
  const { session } = useAuth();
  const query = useQuery({
    queryKey: ME_KEY,
    queryFn: () => apiFetch<Me>("/api/v1/me"),
    enabled: session !== null,
    staleTime: 60_000,
    retry: false,
  });
  const me = query.data;
  useEffect(() => {
    // Spec 015: ids only (never the name or username) for error reports.
    if (me) setObservedUser({ id: me.id, orgId: me.org.id, role: me.role });
  }, [me]);
  return query;
}
