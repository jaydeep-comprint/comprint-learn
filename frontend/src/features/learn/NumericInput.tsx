import { Input } from "@/components/ui/input";

/** A number box with the decimal keyboard on phones and the unit as a suffix (unit entry is 006). */
export function NumericInput({
  id,
  value,
  unit,
  disabled,
  onChange,
  describedBy,
}: {
  id: string;
  value: string;
  unit: string | null;
  disabled?: boolean;
  onChange: (value: string) => void;
  describedBy?: string;
}) {
  return (
    <div className="flex items-center gap-2">
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
      {unit && (
        <span className="text-base text-muted-foreground" data-testid="unit-suffix">
          {unit}
        </span>
      )}
    </div>
  );
}
