import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { Clock, RotateCcw } from "lucide-react";

import { STATUS_LABELS } from "@/features/learn/paths";
import { StatusIcon } from "@/features/learn/StatusIcon";
import type { OutlineConcept } from "@/lib/types";
import { cn } from "@/lib/utils";

import { NODE_H, NODE_W } from "./layoutGraph";

export type ConceptNodeData = {
  concept: OutlineConcept;
  selected: boolean;
  onSelect: (id: string) => void;
};

export type ConceptFlowNode = Node<ConceptNodeData, "concept">;

// Colour + icon + text for each state, never colour alone.
const TONE = {
  locked: "border-border bg-muted text-muted-foreground",
  ready: "border-blue-500 bg-background",
  in_progress: "border-amber-500 bg-amber-50 dark:bg-amber-950/40",
  learned: "border-green-600 bg-green-50 dark:bg-green-950/40",
} as const;

export function ConceptNode({ data }: NodeProps<ConceptFlowNode>) {
  const { concept, selected, onSelect } = data;
  const status = concept.status;
  const fill = concept.kps_total ? (concept.kps_passed / concept.kps_total) * 100 : 0;
  const label = status
    ? `${concept.title}, ${STATUS_LABELS[status]}${
        status === "in_progress" ? `, ${concept.kps_passed} of ${concept.kps_total} parts` : ""
      }`
    : concept.title;
  return (
    <>
      <Handle type="target" position={Position.Top} className="!opacity-0" isConnectable={false} />
      <button
        type="button"
        aria-label={label}
        aria-pressed={selected}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(concept.id);
        }}
        style={{ width: NODE_W, height: NODE_H }}
        className={cn(
          "relative flex items-center gap-2 overflow-hidden rounded-lg border-2 px-3 text-left text-sm shadow-sm",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          status ? TONE[status] : "border-border bg-background",
          selected && "ring-2 ring-ring",
        )}
      >
        {status && <StatusIcon status={status} />}
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 font-medium leading-tight">{concept.title}</span>
          {status && (
            <span className="block text-xs text-muted-foreground">{STATUS_LABELS[status]}</span>
          )}
        </span>
        {concept.waiting && <Clock className="size-4 shrink-0" aria-label="Waiting" />}
        {concept.brush_up && (
          <RotateCcw className="size-4 shrink-0 text-amber-600" aria-label="Brush up" />
        )}
        {status && concept.kps_total > 0 && (
          <span className="absolute inset-x-0 bottom-0 h-1 bg-black/10" aria-hidden>
            <span className="block h-full bg-[var(--success)]" style={{ width: `${fill}%` }} />
          </span>
        )}
      </button>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!opacity-0"
        isConnectable={false}
      />
    </>
  );
}
