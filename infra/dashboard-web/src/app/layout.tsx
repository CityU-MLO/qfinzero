import type { Metadata } from "next";

import { AppProviders } from "@/components/app-providers";
import { Navbar } from "@/components/navbar";

import "./globals.css";

export const metadata: Metadata = {
  title: "QFinZero Data Platform Monitor",
  description: "Health, freshness, and data browsing dashboard for UPQ/NPP/PMB",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <AppProviders>
          <div className="mx-auto max-w-7xl px-4 pb-10 pt-6 md:px-6">
            <Navbar />
            <main>{children}</main>
          </div>
        </AppProviders>
      </body>
    </html>
  );
}
