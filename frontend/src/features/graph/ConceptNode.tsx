import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { Clock, RotateCcw } from "lucide-react";

import { STATUS_LABELS } from "@/features/learn/paths";
import { StatusIcon } from "@/features/learn/StatusIcon";
import type { OutlineConcept } from "@/lib/types";
import { cn } from "@/lib/utils";

import { NODE_H, NODE_W } from "./layoutGraph";
import { DARK_FROM, mastery, masteryFill } from "./mastery";

export type ConceptNodeData = {
  concept: OutlineConcept;
  selected: boolean;
  onSelect: (id: string) => void;
};

export type ConceptFlowNode = Node<ConceptNodeData, "concept">;

// The fill grades white → dark blue with mastery; the icon and status text stay, so colour is
// never the only cue. Locked nodes get a dashed border to set them apart from ready ones.
const BORDER = {
  locked: "border-dashed border-slate-400",
  ready: "border-[var(--mastery-full)]",
  in_progress: "border-[var(--mastery-full)]",
  learned: "border-[var(--mastery-full)]",
} as const;

export function ConceptNode({ data }: NodeProps<ConceptFlowNode>) {
  const { concept, selected, onSelect } = data;
  const status = concept.status;
  const fill = concept.parts_total ? (concept.parts_passed / concept.parts_total) * 100 : 0;
  const m = mastery(concept);
  const dark = m >= DARK_FROM;
  const label = status
    ? `${concept.title}, ${STATUS_LABELS[status]}${
        status === "in_progress" ? `, ${concept.parts_passed} of ${concept.parts_total} parts` : ""
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
        style={{ width: NODE_W, height: NODE_H, background: masteryFill(m) }}
        data-mastery={m.toFixed(2)}
        className={cn(
          "relative flex items-center gap-2 overflow-hidden rounded-lg border-2 px-3 text-left text-sm shadow-sm",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
          dark ? "text-white" : "text-slate-900",
          status ? BORDER[status] : "border-slate-300",
          selected && "ring-2 ring-ring ring-offset-2",
        )}
      >
        {status && <StatusIcon status={status} inheritColor />}
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 font-medium leading-tight">{concept.title}</span>
          {status && (
            <span className={cn("block text-xs", dark ? "text-white" : "text-slate-800")}>
              {STATUS_LABELS[status]}
            </span>
          )}
        </span>
        {concept.waiting && <Clock className="size-4 shrink-0" aria-label="Waiting" />}
        {concept.brush_up && <RotateCcw className="size-4 shrink-0" aria-label="Brush up" />}
        {status === "in_progress" && concept.parts_total > 0 && (
          <span className="absolute inset-x-0 bottom-0 h-1 bg-current/20" aria-hidden>
            <span className="block h-full bg-current/70" style={{ width: `${fill}%` }} />
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
