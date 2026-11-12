/** Pinned, never "latest": the one place the Pyodide version lives. Served by jsDelivr and then
 * browser-cached. No imports: `vite/csp.ts` builds the CSP from it at build time. */
export const PYODIDE_VERSION = "314.0.7";
export const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
