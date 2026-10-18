import { headers } from "next/headers";

import { Navbar } from "@/components/navbar";
import { SiteFooter, SiteHeader } from "@/components/site/site-chrome";

// The documentation is public. Signed-in users keep the console's top bar
// (the hub forwards their identity as x-qfz-user); visitors get the site header.
export default async function DocsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const signedIn = Boolean((await headers()).get("x-qfz-user"));
  return signedIn ? (
    <>
      <Navbar />
      {children}
    </>
  ) : (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      <div className="flex-1">{children}</div>
      <SiteFooter />
    </div>
  );
}
