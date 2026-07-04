"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Whether the page is being served under the /legacy URL prefix (Windows-98 skin).
// Seeded by the server layout from the x-ui-skin request header and exposed to every
// client component so they can render their retro variant automatically (no manual
// theme toggles needed — the URL is the single source of truth).
const LegacySkinContext = React.createContext(false);

export function useLegacySkin(): boolean {
  return React.useContext(LegacySkinContext);
}

export function AppProviders({
  children,
  legacy = false,
}: {
  children: React.ReactNode;
  legacy?: boolean;
}) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return (
    <LegacySkinContext.Provider value={legacy}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </LegacySkinContext.Provider>
  );
}
