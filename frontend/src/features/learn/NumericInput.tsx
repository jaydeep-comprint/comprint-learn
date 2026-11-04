import { useId } from "react";

import { Input } from "@/components/ui/input";
import { unitPlaceholder, unitPreview } from "@/features/learn/unitPreview";

/** A number box with the decimal keyboard on phones. When the answer has a unit (spec 006), a
 * unit box sits beside it: the student types any unit of that quantity, with a live
 * "Read as: m·s⁻¹" preview (display only; the server decides). */
export function NumericInput({
  id,
  value,
  unit,
  unitRequired = false,
  unitValue = "",
  disabled,
  onChange,
  onUnitChange,
  describedBy,
}: {
  id: string;
  value: string;
  /** The authored unit (the placeholder's example). */
  unit: string | null;
  unitRequired?: boolean;
  unitValue?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  onUnitChange?: (value: string) => void;
  describedBy?: string;
}) {
  const unitId = useId();
  const previewId = `${unitId}-preview`;
  const preview = unitRequired ? unitPreview(unitValue) : null;
  return (
    <div className="flex flex-wrap items-start gap-2">
      <Input
        id={id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        maxLength={200}
        value={value}
        disabled={disabled}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-48 text-base"
      />
      {unitRequired ? (
        <div className="w-32 space-y-1">
          <Input
            id={unitId}
            type="text"
            inputMode="text"
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            maxLength={40}
            value={unitValue}
            disabled={disabled}
            aria-label="Unit"
            aria-describedby={previewId}
            placeholder={unitPlaceholder(unit)}
            onChange={(e) => onUnitChange?.(e.target.value)}
            className="text-base"
            data-testid="unit-input"
          />
          <p id={previewId} className="min-h-4 text-xs text-muted-foreground" aria-live="polite">
            {unitValue.trim() ? (preview ? `Read as: ${preview}` : "Not a unit we know") : ""}
          </p>
        </div>
      ) : (
        unit && (
          <span className="pt-2 text-base text-muted-foreground" data-testid="unit-suffix">
            {unit}
          </span>
        )
      )}
    </div>
  );
}
