import * as React from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";

type Variant = "info" | "success" | "warning" | "error";

const STYLE: Record<Variant, string> = {
  info: "border-primary/25 bg-primary/5 text-foreground [&>svg]:text-primary",
  success: "border-success/25 bg-success/5 text-foreground [&>svg]:text-success",
  warning: "border-warning/30 bg-warning/5 text-foreground [&>svg]:text-warning",
  error: "border-destructive/30 bg-destructive/5 text-foreground [&>svg]:text-destructive",
};
const ICON = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle };

/** Inline message box. */
export function Alert({
  variant = "info",
  title,
  children,
  className,
}: {
  variant?: Variant;
  title?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const Icon = ICON[variant];
  return (
    <div role={variant === "error" ? "alert" : "status"}
      className={cn("flex gap-2.5 rounded-md border px-3 py-2.5 text-sm", STYLE[variant], className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 space-y-0.5">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className="text-[13px] text-muted-foreground [&_code]:text-foreground">{children}</div>}
      </div>
    </div>
  );
}
