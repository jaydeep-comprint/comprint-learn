/** `[1, "a"]` → `f(1, "a")`: a test's JSON-text args shown as the call it makes. */
export function callText(entry: string, args: string): string {
  const inner = args.trim().replace(/^\[/, "").replace(/\]$/, "");
  return `${entry}(${inner})`;
}
