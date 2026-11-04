/**
 * "Read as: m·s⁻¹" under the unit box: the same aliases as the server
 * (backend/app/grading/units.py), for display only. The server decides what a unit means.
 */

/** Units the server knows (backend/app/content/units.py `UNITS`). Case-sensitive. */
export const KNOWN_UNITS = new Set([
  "m",
  "km",
  "cm",
  "mm",
  "s",
  "ms",
  "min",
  "h",
  "kg",
  "g",
  "N",
  "J",
  "kJ",
  "W",
  "kW",
  "Pa",
  "Hz",
  "V",
  "A",
  "ohm",
  "C",
  "K",
  "L",
]);

export const ALIASES: Record<string, string> = {
  kmph: "(km/h)",
  kph: "(km/h)",
  hr: "h",
  hrs: "h",
  mps: "(m/s)",
  sec: "s",
  secs: "s",
  kgs: "kg",
  Ω: "ohm",
};

/** What the student typed → the server's unit syntax (aliases, ², ³, ·, spaces). */
export function normaliseUnit(text: string): string {
  let out = text
    .trim()
    .replaceAll("²", "^2")
    .replaceAll("³", "^3")
    .replaceAll("·", "*")
    .replaceAll("⁻¹", "^-1")
    .replaceAll("⁻²", "^-2")
    .replaceAll("−", "-");
  out = out.replace(/(?<=[A-Za-z0-9)Ω])\s+(?=[A-Za-z(Ω])/g, "*").replace(/\s+/g, "");
  return out.replace(/[A-Za-zΩ]+/g, (name) => ALIASES[name] ?? name);
}

const SUPERSCRIPT: Record<string, string> = {
  "-": "⁻",
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};

type Factors = Map<string, number>;

/** A tiny parser for products/quotients of known units with integer powers and parentheses. */
function parse(src: string): Factors | null {
  let i = 0;
  const peek = () => src[i];

  function atom(): Factors | null {
    if (peek() === "(") {
      i++;
      const inner = expr();
      if (inner === null || peek() !== ")") return null;
      i++;
      return power(inner);
    }
    const m = /^[A-Za-z]+/.exec(src.slice(i));
    if (!m || !KNOWN_UNITS.has(m[0])) return null;
    i += m[0].length;
    return power(new Map([[m[0], 1]]));
  }

  function power(f: Factors): Factors | null {
    const m = /^(\^|\*\*)(-?\d+)/.exec(src.slice(i));
    if (!m) return f;
    i += m[0].length;
    const n = Number(m[2]);
    return new Map([...f].map(([k, v]) => [k, v * n]));
  }

  function expr(): Factors | null {
    const acc = atom();
    while (acc !== null && (peek() === "*" || peek() === "/")) {
      const op = src[i++];
      const next = atom();
      if (next === null) return null;
      for (const [k, v] of next) acc.set(k, (acc.get(k) ?? 0) + (op === "/" ? -v : v));
    }
    return acc;
  }

  const out = expr();
  return out !== null && i === src.length ? out : null;
}

/** "km/hr" → "km·h⁻¹"; null when it can't be read (the server will say so too). */
export function unitPreview(text: string): string | null {
  if (!text.trim() || text.length > 40) return null;
  const factors = parse(normaliseUnit(text));
  if (factors === null) return null;
  const parts = [...factors]
    .filter(([, n]) => n !== 0)
    .map(([u, n]) => (n === 1 ? u : u + [...String(n)].map((c) => SUPERSCRIPT[c] ?? c).join("")));
  return parts.length ? parts.join("·") : null;
}

/** "m/s" → "speed": the box's placeholder ("unit, e.g. m/s"). */
export function unitPlaceholder(authored: string | null): string {
  return authored ? `unit, e.g. ${authored}` : "unit";
}
