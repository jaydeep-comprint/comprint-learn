/** Click-to-highlight: a concept and all its ancestors. Direct prerequisites (and their edges into
 * the concept) at full strength, more distant ancestors at medium, everything else dimmed. */

export type Strength = "selected" | "direct" | "distant" | "dim";

export type Highlight = {
  nodes: Map<string, Strength>;
  /** Keyed `${from}->${to}`. */
  edges: Map<string, Exclude<Strength, "selected">>;
};

export function edgeId(from: string, to: string): string {
  return `${from}->${to}`;
}

/** `prereqs`: concept → its direct prerequisites (within the map). */
export function highlight(
  selected: string,
  prereqs: Map<string, string[]>,
  edges: [string, string][],
): Highlight {
  const direct = new Set(prereqs.get(selected) ?? []);
  const ancestors = new Set<string>();
  const stack = [...direct];
  while (stack.length) {
    const id = stack.pop()!;
    if (ancestors.has(id) || id === selected) continue;
    ancestors.add(id);
    stack.push(...(prereqs.get(id) ?? []));
  }
  const nodes = new Map<string, Strength>();
  for (const id of prereqs.keys()) {
    nodes.set(
      id,
      id === selected
        ? "selected"
        : direct.has(id)
          ? "direct"
          : ancestors.has(id)
            ? "distant"
            : "dim",
    );
  }
  const lit = new Set([selected, ...ancestors]);
  const out = new Map<string, Exclude<Strength, "selected">>();
  for (const [from, to] of edges) {
    let s: Exclude<Strength, "selected"> = "dim";
    if (ancestors.has(from) && lit.has(to)) s = to === selected ? "direct" : "distant";
    out.set(edgeId(from, to), s);
  }
  return { nodes, edges: out };
}

export const OPACITY: Record<Strength, number> = {
  selected: 1,
  direct: 1,
  distant: 0.65,
  dim: 0.3,
};
