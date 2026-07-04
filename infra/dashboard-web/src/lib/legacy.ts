// Hidden Windows-98 skin ("legacy UI"). It lives at the /legacy URL prefix: visiting
// /legacy (or /legacy/data, /legacy/pmb, …) renders the very same pages with the retro
// skin, while the plain routes (/, /data, …) stay modern. The URL stays at /legacy —
// middleware rewrites it internally to the real page and flags the skin via a request
// header that the root layout reads. Nothing in the modern UI links to /legacy.

export const LEGACY_PREFIX = "/legacy";
export const SKIN_HEADER = "x-ui-skin";
export const SKIN_LEGACY = "legacy";
