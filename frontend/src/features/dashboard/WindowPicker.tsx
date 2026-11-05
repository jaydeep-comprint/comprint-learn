import type { DashboardWindow } from "@/lib/types";
import { cn } from "@/lib/utils";

const OPTIONS: { value: DashboardWindow; label: string }[] = [
  { value: "7d", label: "7 d" },
  { value: "30d", label: "30 d" },
  { value: "all", label: "All" },
];

/** The analytics window (spec 010): 7 days (default), 30 days or all time. */
export function WindowPicker({
  value,
  onChange,
}: {
  value: DashboardWindow;
  onChange: (w: DashboardWindow) => void;
}) {
  return (
    <div role="group" aria-label="Time window" className="inline-flex rounded-md border p-0.5">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded px-3 py-1 text-sm",
            value === o.value ? "bg-primary text-primary-foreground" : "hover:bg-muted",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
