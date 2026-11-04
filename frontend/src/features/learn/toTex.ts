/** A rough LaTeX rendering of what the student typed, for the live preview only (the server parses
 * and grades the raw text). */
export function toTex(text: string): string {
  return text
    .replace(/\*\*/g, "^")
    .replace(/sqrt\(([^()]*)\)/g, "\\sqrt{$1}")
    .replace(/\^\(([^()]*)\)/g, "^{$1}")
    .replace(/\^(-?[0-9.]+|[A-Za-z])/g, "^{$1}")
    .replace(/\bpi\b/g, "\\pi ")
    .replace(/\*/g, " \\cdot ");
}
