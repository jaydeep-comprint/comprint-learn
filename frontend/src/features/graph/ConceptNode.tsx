import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { AlertTriangle, Clock, RotateCcw } from "lucide-react";

import { BAND_FILL, BAND_LABELS, MEMORY_GREY } from "@/features/dashboard/heat";
import { STATUS_LABELS } from "@/features/learn/paths";
import { StatusIcon } from "@/features/learn/StatusIcon";
import type { Band, HeatState, OutlineConcept } from "@/lib/types";
import { cn } from "@/lib/utils";

import { NODE_H, NODE_W } from "./layoutGraph";
import { DARK_FROM, mastery, masteryFill } from "./mastery";

/** Teacher views (spec 010) add the 5-state `state` and a memory band. */
export type MapConcept = OutlineConcept & {
  state?: HeatState;
  memory?: { band: Band } | null;
};

export type MapMode = "progress" | "memory";

export type ConceptNodeData = {
  concept: MapConcept;
  selected: boolean;
  onSelect: (id: string) => void;
  mode?: MapMode;
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
  const { concept, selected, onSelect, mode = "progress" } = data;
  const status = concept.status;
  const fill = concept.parts_total ? (concept.parts_passed / concept.parts_total) * 100 : 0;
  const m = mastery(concept);
  const memory = mode === "memory";
  const band = concept.memory?.band ?? "none";
  const learned = status === "learned";
  const dark = memory ? learned && band === "strong" : m >= DARK_FROM;
  const background = memory ? (learned ? BAND_FILL[band] : MEMORY_GREY) : masteryFill(m);
  const stuck = concept.state === "stuck";
  const label = status
    ? `${concept.title}, ${STATUS_LABELS[status]}${
        status === "in_progress" ? `, ${concept.parts_passed} of ${concept.parts_total} parts` : ""
      }${stuck ? ", stuck" : ""}${memory && learned ? `, ${BAND_LABELS[band]}` : ""}`
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
        style={{ width: NODE_W, height: NODE_H, background }}
        data-mastery={m.toFixed(2)}
        data-band={memory && learned ? band : undefined}
        className={cn(
          "relative flex items-center gap-2 overflow-hidden rounded-lg border-2 px-3 text-left text-sm shadow-sm",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
          dark ? "text-white" : "text-slate-900",
          status ? BORDER[status] : "border-slate-300",
          memory && !learned && "opacity-60",
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
        {stuck && !memory && (
          <AlertTriangle className="size-4 shrink-0 text-red-600" aria-label="Stuck" />
        )}
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
