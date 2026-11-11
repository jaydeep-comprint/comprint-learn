import { useCallback, useState } from "react";

/** Row selection for the consent bulk bar (spec 014). */
export function useSelection() {
  const [ids, setIds] = useState<ReadonlySet<string>>(() => new Set());
  const set = useCallback((changed: string[], on: boolean) => {
    setIds((prev) => {
      const next = new Set(prev);
      for (const id of changed) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);
  const clear = useCallback(() => setIds(new Set()), []);
  return { ids, size: ids.size, has: (id: string) => ids.has(id), set, clear };
}
