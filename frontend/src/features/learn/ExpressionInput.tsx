import katex from "katex";
import { useMemo } from "react";

import { Input } from "@/components/ui/input";
import { toTex } from "@/features/learn/toTex";

export function ExpressionInput({
  id,
  value,
  variables,
  disabled,
  onChange,
}: {
  id: string;
  value: string;
  variables: string[] | null;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const preview = useMemo(
    () =>
      value.trim()
        ? katex.renderToString(toTex(value), { throwOnError: false, output: "html" })
        : "",
    [value],
  );
  const hintId = `${id}-hint`;
  return (
    <div className="space-y-2">
      <Input
        id={id}
        type="text"
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        maxLength={200}
        value={value}
        disabled={disabled}
        aria-describedby={hintId}
        onChange={(e) => onChange(e.target.value)}
        className="font-mono text-base"
      />
      <p id={hintId} className="text-sm text-muted-foreground">
        Use ^ for powers, e.g. 3x^2 + 2
        {variables && variables.length > 0 && <> · Use {variables.join(", ")}</>}
      </p>
      <div
        data-testid="expression-preview"
        aria-live="polite"
        aria-label="Preview"
        className="min-h-8 rounded-md bg-muted/50 px-3 py-1"
        // KaTeX escapes the input; the preview is display-only.
        dangerouslySetInnerHTML={{ __html: preview }}
      />
    </div>
  );
}
