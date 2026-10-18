import type { Metadata } from "next";
import { headers } from "next/headers";

import { AppProviders } from "@/components/app-providers";
import { SKIN_HEADER, SKIN_LEGACY } from "@/lib/legacy";
import { cn } from "@/lib/utils";

import "./globals.css";
import "./legacy.css";

export const metadata: Metadata = {
  title: { default: "QFinZero", template: "%s · QFinZero" },
  description:
    "A point-in-time trading environment for LLM agents: market data, news and a paper broker behind one time-locked API.",
};

// Root layout: providers only. The public site, (site), and the signed-in
// console, (console), add their own chrome.
export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Hidden Windows-98 skin: active for the /legacy URL prefix (flagged by middleware).
  const legacy = (await headers()).get(SKIN_HEADER) === SKIN_LEGACY;
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={cn("font-sans antialiased", legacy && "legacy")}>
        <AppProviders legacy={legacy}>{children}</AppProviders>
      </body>
    </html>
  );
}
