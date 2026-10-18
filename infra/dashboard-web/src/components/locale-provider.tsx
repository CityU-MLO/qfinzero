"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Languages } from "lucide-react";

import { LOCALE_COOKIE, tr, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Ctx = { locale: Locale; setLocale: (l: Locale) => void };

const LocaleContext = React.createContext<Ctx>({ locale: "en", setLocale: () => undefined });

export function LocaleProvider({ initial, children }: { initial: Locale; children: React.ReactNode }) {
  const router = useRouter();
  const [locale, set] = React.useState<Locale>(initial);
  const setLocale = React.useCallback(
    (l: Locale) => {
      document.cookie = `${LOCALE_COOKIE}=${l}; path=/; max-age=31536000; samesite=lax`;
      document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
      set(l);
      router.refresh(); // re-render server components in the new language
    },
    [router],
  );
  return <LocaleContext.Provider value={{ locale, setLocale }}>{children}</LocaleContext.Provider>;
}

export function useLocale() {
  return React.useContext(LocaleContext);
}

/** ``t(en, zh)`` for the current language. */
export function useT() {
  const { locale } = useLocale();
  return React.useCallback((en: string, zh: string) => tr(locale, en, zh), [locale]);
}

/** EN / 中文 switch. */
export function LanguageToggle({ className }: { className?: string }) {
  const { locale, setLocale } = useLocale();
  const next: Locale = locale === "en" ? "zh" : "en";
  return (
    <button
      type="button"
      onClick={() => setLocale(next)}
      title={locale === "en" ? "切换到中文" : "Switch to English"}
      className={cn(
        "flex h-8 items-center gap-1 rounded-md px-2 text-[13px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground",
        className,
      )}
    >
      <Languages className="h-4 w-4" />
      {locale === "en" ? "中文" : "EN"}
    </button>
  );
}
