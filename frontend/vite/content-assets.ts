// Serves content images (content/<course>/<chapter>/<concept>/img/*) at /content-assets/... in dev
// and copies them into the build, so they ship on the CDN. Only image extensions are ever served:
// never the YAML or Markdown, which hold answer keys.
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import type { Plugin } from "vite";

export const URL_PREFIX = "/content-assets/";

const TYPES: Record<string, string> = {
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
};

// <course>/<chapter-folder>/<concept>/img/<file...>
const ASSET_PATH = /^[a-z0-9-]+\/\d{2}-[a-z0-9-]+\/[a-z0-9-]+\/img\/[A-Za-z0-9._/-]+$/;

/** True if `rel` (posix, relative to content/) is an image a client may fetch. */
export function isAllowedAsset(rel: string): boolean {
  if (
    !ASSET_PATH.test(rel) ||
    rel.split("/").some((part) => part === ".." || part.startsWith("."))
  ) {
    return false;
  }
  return path.posix.extname(rel).toLowerCase() in TYPES;
}

/** Every allowed asset under `root`, as posix paths relative to it. */
export function collectAssets(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      if (name.startsWith(".")) continue;
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else {
        const rel = path.relative(root, full).split(path.sep).join("/");
        if (isAllowedAsset(rel)) out.push(rel);
      }
    }
  };
  walk(root);
  return out.sort();
}

export function contentAssets(root: string): Plugin {
  const contentRoot = path.resolve(root);
  return {
    name: "content-assets",
    configureServer(server) {
      server.middlewares.use(URL_PREFIX, (req, res, next) => {
        let rel: string;
        try {
          rel = decodeURIComponent((req.url ?? "").split("?")[0]!.replace(/^\//, ""));
        } catch {
          return next();
        }
        const full = path.resolve(contentRoot, rel);
        if (!isAllowedAsset(rel) || !full.startsWith(contentRoot + path.sep)) return next();
        let body: Buffer;
        try {
          body = readFileSync(full);
        } catch {
          return next();
        }
        res.setHeader("Content-Type", TYPES[path.extname(full).toLowerCase()]!);
        // Content SVGs are validated (no scripts), and this blocks them anyway if opened directly.
        res.setHeader("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'");
        res.setHeader("X-Content-Type-Options", "nosniff");
        res.end(body);
      });
    },
    generateBundle() {
      for (const rel of collectAssets(contentRoot)) {
        this.emitFile({
          type: "asset",
          fileName: `${URL_PREFIX.slice(1)}${rel}`,
          source: readFileSync(path.join(contentRoot, rel)),
        });
      }
    },
  };
}
