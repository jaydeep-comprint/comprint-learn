import "@xyflow/react/dist/style.css";

import { Controls, type Edge, MarkerType, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { Outline } from "@/lib/types";

import { ConceptNode, type ConceptFlowNode } from "./ConceptNode";
import { ConceptPanel } from "./ConceptPanel";
import { edgeId, highlight, OPACITY } from "./highlight";
import { layoutGraph } from "./layoutGraph";

const nodeTypes = { concept: ConceptNode };

/** The course outline as a graph (lazily loaded: the list view never pulls in React Flow). */
export default function CourseMap({
  course,
  outline,
  onShowList,
}: {
  course: string;
  outline: Outline;
  onShowList: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const concepts = useMemo(() => outline.chapters.flatMap((ch) => ch.concepts), [outline]);
  const ids = useMemo(() => new Set(concepts.map((c) => c.id)), [concepts]);
  const edges = useMemo(
    () =>
      concepts.flatMap((c) =>
        c.prereqs.filter((p) => ids.has(p)).map((p): [string, string] => [p, c.id]),
      ),
    [concepts, ids],
  );
  const prereqs = useMemo(
    () => new Map(concepts.map((c) => [c.id, c.prereqs.filter((p) => ids.has(p))])),
    [concepts, ids],
  );
  const placed = useMemo(() => layoutGraph(concepts, edges), [concepts, edges]);
  const lit = useMemo(
    () => (selected ? highlight(selected, prereqs, edges) : null),
    [selected, prereqs, edges],
  );

  const clear = useCallback(() => setSelected(null), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && clear();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clear]);

  const byId = useMemo(() => new Map(concepts.map((c) => [c.id, c])), [concepts]);
  const nodes: ConceptFlowNode[] = placed.map((p) => {
    const concept = byId.get(p.id)!;
    return {
      id: p.id,
      type: "concept",
      position: { x: p.x, y: p.y },
      data: { concept, selected: selected === p.id, onSelect: setSelected },
      style: { opacity: lit ? OPACITY[lit.nodes.get(p.id) ?? "dim"] : 1 },
      draggable: false,
      selectable: false,
      focusable: false,
    };
  });
  const flowEdges: Edge[] = edges.map(([from, to]) => {
    const strength = lit?.edges.get(edgeId(from, to));
    const strong = strength === "direct";
    return {
      id: edgeId(from, to),
      source: from,
      target: to,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: {
        opacity: lit ? OPACITY[strength ?? "dim"] : 1,
        strokeWidth: strong ? 2.5 : 1.5,
      },
      focusable: false,
    };
  });

  const staff = concepts.every((c) => c.status === null);
  return (
    <div className="space-y-2">
      <div className="relative h-[70vh] min-h-96 w-full overflow-hidden rounded-lg border">
        <button
          type="button"
          onClick={onShowList}
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-20 focus:rounded focus:bg-background focus:px-3 focus:py-2"
        >
          View as list
        </button>
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.3}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            onPaneClick={clear}
          >
            <Controls showInteractive={false} />
          </ReactFlow>
        </ReactFlowProvider>
        <ConceptPanel
          course={course}
          outline={outline}
          concept={selected ? (byId.get(selected) ?? null) : null}
          onClose={clear}
        />
      </div>
      {!staff && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" aria-hidden>
          <span>No knowledge</span>
          <span
            className="h-2 w-32 rounded-full border"
            style={{
              background: "linear-gradient(to right, var(--mastery-empty), var(--mastery-full))",
            }}
          />
          <span>Learned</span>
        </div>
      )}
    </div>
  );
}
