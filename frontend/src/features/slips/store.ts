import { useSyncExternalStore } from "react";

import type { Slip } from "@/lib/types";

/**
 * Temp passwords for the slips view, held in memory only: never in storage, the URL or history
 * state. A reload or sign-out loses them, which is the point.
 */
export type SlipBatch = { slips: Slip[]; backTo: string; backLabel: string };

let batch: SlipBatch | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

export const slipsStore = {
  set(next: SlipBatch) {
    batch = next;
    emit();
  },
  clear() {
    batch = null;
    emit();
  },
  get(): SlipBatch | null {
    return batch;
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export function useSlips(): SlipBatch | null {
  return useSyncExternalStore(slipsStore.subscribe, slipsStore.get);
}
