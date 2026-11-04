// Content images live next to each concept (`img/<file>`, the only form the validator allows) and
// are served at `{asset_base}img/<file>`. Anything else is not rendered.
const CONTENT_IMAGE = /^img\/[A-Za-z0-9._-]+(\/[A-Za-z0-9._-]+)*$/;

/** The URL to load, or null if the image must not be rendered. */
export function rewriteImageSrc(src: string | undefined | null, assetBase: string): string | null {
  if (!src || !assetBase || !CONTENT_IMAGE.test(src)) return null;
  if (src.split("/").some((part) => part === ".." || part.startsWith("."))) return null;
  return `${assetBase}${src}`;
}
