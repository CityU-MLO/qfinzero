"use client";

import { ArrowRight, LineChart, Wallet } from "lucide-react";

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
  return (
    <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
        <Choice
          icon={Wallet}
          title="Open an account"
          body="Set starting capital, market and margin for a new paper account."
          action="Set up"
          onClick={onAllocate}
        />
        <Choice
          icon={LineChart}
          title="Trade an account"
          body="Pick an account and a start date, then step through the session and trade."
          action="Start a session"
          onClick={onEnter}
        />
    </div>
  );
}
