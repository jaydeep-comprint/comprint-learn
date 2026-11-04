/** Map layout computed by us (no dagre): layer = longest path from a root among the outline's
 * concepts (prerequisites above), nodes in a layer ordered by outline index, fixed node size. */

export const NODE_W = 200;
export const NODE_H = 64;
export const GAP_X = 48;
export const GAP_Y = 72;

export type Placed = { id: string; x: number; y: number };

/** `concepts` in outline order; `edges` as [prerequisite, dependant] pairs (outside ones ignored). */
export function layoutGraph(concepts: { id: string }[], edges: [string, string][]): Placed[] {
  const ids = concepts.map((c) => c.id);
  const known = new Set(ids);
  const prereqs = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const [from, to] of edges) {
    if (known.has(from) && known.has(to) && from !== to) prereqs.get(to)!.push(from);
  }
  const layer = new Map<string, number>();
  const visiting = new Set<string>();
  const depth = (id: string): number => {
    const done = layer.get(id);
    if (done !== undefined) return done;
    if (visiting.has(id)) return 0; // a cycle (the validator forbids them): break it
    visiting.add(id);
    const d = Math.max(-1, ...prereqs.get(id)!.map(depth)) + 1;
    visiting.delete(id);
    layer.set(id, d);
    return d;
  };
  ids.forEach(depth);

  const rows = new Map<number, string[]>();
  for (const id of ids) {
    const d = layer.get(id)!;
    rows.set(d, [...(rows.get(d) ?? []), id]); // outline order within a layer
  }
  const widest = Math.max(0, ...[...rows.values()].map((r) => r.length));
  const out: Placed[] = [];
  for (const [d, row] of rows) {
    const offset = ((widest - row.length) * (NODE_W + GAP_X)) / 2; // centre each layer
    row.forEach((id, i) =>
      out.push({ id, x: offset + i * (NODE_W + GAP_X), y: d * (NODE_H + GAP_Y) }),
    );
  }
  return out.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
}
