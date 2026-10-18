import { headers } from "next/headers";

import { Navbar } from "@/components/navbar";
import { LegacyBanner, LegacyFooter } from "@/components/legacy/legacy-chrome";
import { SKIN_HEADER, SKIN_LEGACY } from "@/lib/legacy";

export const metadata = { title: "Console" };

export default async function ConsoleLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const legacy = (await headers()).get(SKIN_HEADER) === SKIN_LEGACY;
  return (
    <>
      {legacy && <LegacyBanner />}
      <Navbar />
      <main className="mx-auto max-w-7xl px-4 pb-12 pt-6 md:px-6">{children}</main>
      {legacy && <LegacyFooter />}
    </>
  );
}
