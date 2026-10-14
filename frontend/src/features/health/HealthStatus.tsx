import { useQuery } from "@tanstack/react-query";

import { ApiError, apiGet } from "../../lib/api";

type HealthResponse = { status: "ok" | "error"; db: "ok" | "error" };

export function HealthStatus() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<HealthResponse>("/api/v1/health"),
    retry: 1,
  });

  if (isPending) {
    return <p className="text-slate-600">Checking API…</p>;
  }

  if (data) {
    return <p className="font-medium text-green-700">API: ok · Database: ok</p>;
  }

  // The API answered but reported the database as down.
  if (error instanceof ApiError && error.status === 503) {
    return <p className="font-medium text-amber-700">API: ok · Database: unreachable</p>;
  }

  return (
    <div className="flex items-center gap-3">
      <p className="font-medium text-red-700">API: unreachable</p>
      <button
        type="button"
        onClick={() => void refetch()}
        disabled={isFetching}
        className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50"
      >
        {isFetching ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}
