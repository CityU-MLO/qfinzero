"use client";

import { ArrowRight, LineChart, Wallet } from "lucide-react";

import { useT } from "@/components/locale-provider";

function Choice({
  icon: Icon,
  title,
  body,
  action,
  onClick,
}: {
  icon: typeof Wallet;
  title: string;
  body: string;
  action: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group flex flex-col items-start gap-2 rounded-lg border bg-card p-5 text-left transition-colors hover:border-primary/40 hover:bg-muted/40"
    >
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" />
        <span className="font-semibold">{title}</span>
      </div>
      <p className="text-sm text-muted-foreground">{body}</p>
      <span className="mt-1 flex items-center gap-1 text-sm font-medium text-primary">
        {action} <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
      </span>
    </button>
  );
}

export function Landing({ onAllocate, onEnter }: { onAllocate: () => void; onEnter: () => void }) {
  const t = useT();
  return (
    <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
        <Choice
          icon={Wallet}
          title={t("Open an account", "开立账户")}
          body={t(
            "Set starting capital, market and margin for a new paper account.",
            "为新的模拟账户设置初始资金、市场和保证金。",
          )}
          action={t("Set up", "去设置")}
          onClick={onAllocate}
        />
        <Choice
          icon={LineChart}
          title={t("Trade an account", "交易账户")}
          body={t(
            "Pick an account and a start date, then step through the session and trade.",
            "选择账户和开始日期，然后逐步推进会话并交易。",
          )}
          action={t("Start a session", "开始会话")}
          onClick={onEnter}
        />
    </div>
  );
}
