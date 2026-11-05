import type { Query } from "./DashCard";

export function pct(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

/** A part of a query's data, keeping its loading and error state. */
export function part<T, U>(q: Query<T>, f: (data: T) => U): Query<U> {
  return {
    data: q.data === undefined ? undefined : f(q.data),
    isPending: q.isPending,
    isError: q.isError,
    refetch: q.refetch,
  };
}
