import { headers } from "next/headers";

import { Navbar } from "@/components/navbar";
import { SiteFooter, SiteHeader } from "@/components/site/site-chrome";

// The documentation is public. Signed-in users keep the console's top bar
// (the hub forwards their identity as x-qfz-user); visitors get the site header.
export default async function DocsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const signedIn = Boolean((await headers()).get("x-qfz-user"));
  // --nav-h: height of the sticky bar above the docs bar (console 48px, site 56px)
  return signedIn ? (
    <div style={{ "--nav-h": "48px" } as React.CSSProperties} className="min-h-screen bg-card">
      <Navbar />
      {children}
    </div>
  ) : (
    <div style={{ "--nav-h": "56px" } as React.CSSProperties} className="flex min-h-screen flex-col bg-card">
      <SiteHeader />
      <div className="flex-1">{children}</div>
      <SiteFooter />
    </div>
  );
}
