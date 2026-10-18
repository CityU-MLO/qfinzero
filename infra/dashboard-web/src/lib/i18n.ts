// Two UI languages. Strings live next to the code that shows them as
// (english, chinese) pairs:  t("Sign in", "登录").  The choice is stored in the
// qfz_lang cookie so server components render the same language as the client.

export type Locale = "en" | "zh";

export const LOCALES: readonly Locale[] = ["en", "zh"];
export const LOCALE_COOKIE = "qfz_lang";
export const LOCALE_LABEL: Record<Locale, string> = { en: "English", zh: "中文" };

export function isLocale(x: unknown): x is Locale {
  return x === "en" || x === "zh";
}

/** Locale from the cookie, else from Accept-Language, else English. */
export function pickLocale(cookie: string | undefined | null, acceptLanguage?: string | null): Locale {
  if (isLocale(cookie)) return cookie;
  return /^\s*zh\b/i.test(acceptLanguage ?? "") ? "zh" : "en";
}

export function tr(locale: Locale, en: string, zh: string): string {
  return locale === "zh" ? zh : en;
}

/** Number formatting locale for Intl APIs. */
export function intlLocale(locale: Locale): string {
  return locale === "zh" ? "zh-CN" : "en-US";
}
