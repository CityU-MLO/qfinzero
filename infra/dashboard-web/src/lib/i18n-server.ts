import { cookies, headers } from "next/headers";

import { LOCALE_COOKIE, pickLocale, tr, type Locale } from "@/lib/i18n";

/** The request's locale, for server components. */
export async function getLocale(): Promise<Locale> {
  const [c, h] = await Promise.all([cookies(), headers()]);
  return pickLocale(c.get(LOCALE_COOKIE)?.value, h.get("accept-language"));
}

/** ``t(en, zh)`` bound to the request's locale. */
export async function getT() {
  const locale = await getLocale();
  return (en: string, zh: string) => tr(locale, en, zh);
}
