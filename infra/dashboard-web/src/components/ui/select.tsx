import * as React from "react";

import { cn } from "@/lib/utils";

function Select({ className, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm focus-visible:outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export { Select };
