import type { Metadata } from "next";
import { headers } from "next/headers";

import { AppProviders } from "@/components/app-providers";
import { Navbar } from "@/components/navbar";
import { LegacyBanner, LegacyFooter } from "@/components/legacy/legacy-chrome";
import { SKIN_HEADER, SKIN_LEGACY } from "@/lib/legacy";
import { cn } from "@/lib/utils";

import "./globals.css";
import "./legacy.css";

export const metadata: Metadata = {
  title: "QFinZero Console",
  description: "Chat-first agent console for QFinZero — chat, data, PMB, settings, docs",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Hidden Windows-98 skin: active for the /legacy URL prefix (flagged by middleware).
  const legacy = (await headers()).get(SKIN_HEADER) === SKIN_LEGACY;

  return (
    <html lang="en" suppressHydrationWarning>
      <body className={cn("font-sans antialiased", legacy && "legacy")}>
        <AppProviders legacy={legacy}>
          {legacy && <LegacyBanner />}
          <div className="mx-auto max-w-7xl px-4 pb-10 pt-6 md:px-6">
            <Navbar />
            <main>{children}</main>
            {legacy && <LegacyFooter />}
          </div>
        </AppProviders>
      </body>
    </html>
  );
}
