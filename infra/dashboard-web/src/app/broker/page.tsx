"use client";

import { useState } from "react";

import { Landing } from "@/components/broker/landing";
import { AllocatePanel } from "@/components/broker/allocate-panel";
import { EnterPanel } from "@/components/broker/enter-panel";
import { Terminal } from "@/components/broker/terminal";

type View = "landing" | "allocate" | "enter" | "terminal";

interface Live {
  sessionId: string;
  accountId: string;
  watchlist: string[];
}

export default function BrokerPage() {
  const [view, setView] = useState<View>("landing");
  const [presetAccount, setPresetAccount] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);

  return (
    // Full-screen immersive broker — escapes the console chrome behind it.
    <div className="fixed inset-0 z-50 overflow-hidden bg-slate-950 text-slate-200">
      <div className="h-full w-full overflow-y-auto">
        {view === "landing" && (
          <Landing
            onAllocate={() => setView("allocate")}
            onEnter={() => {
              setPresetAccount(null);
              setView("enter");
            }}
          />
        )}

        {view === "allocate" && (
          <AllocatePanel
            onBack={() => setView("landing")}
            onCreated={(accountId) => {
              setPresetAccount(accountId);
              setView("enter");
            }}
          />
        )}

        {view === "enter" && (
          <EnterPanel
            presetAccountId={presetAccount}
            onBack={() => setView("landing")}
            onEnter={(l) => {
              setLive(l);
              setView("terminal");
            }}
          />
        )}

        {view === "terminal" && live && (
          <div className="h-full">
            <Terminal
              sessionId={live.sessionId}
              accountId={live.accountId}
              watchlist={live.watchlist}
              onExit={() => {
                setLive(null);
                setView("landing");
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
