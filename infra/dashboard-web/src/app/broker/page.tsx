"use client";

import { useState } from "react";
import { MonitorPlay } from "lucide-react";

import { useLegacySkin } from "@/components/app-providers";
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
  const legacy = useLegacySkin();
  const [view, setView] = useState<View>("landing");
  const [presetAccount, setPresetAccount] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);

  return (
    // Full-screen immersive broker — escapes the console chrome behind it.
    <div
      className={`fixed inset-0 z-50 overflow-hidden bg-slate-950 text-slate-200 ${
        legacy ? "broker-98" : ""
      }`}
    >
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

      {/* Retro skin toggle — the Win98 broker lives at /legacy/broker. */}
      <a
        href={legacy ? "/broker" : "/legacy/broker"}
        className="broker-skin-toggle fixed bottom-3 left-3 z-[60] flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/90 px-3 py-1.5 text-xs text-slate-300 shadow-lg hover:bg-slate-800"
      >
        <MonitorPlay className="h-3.5 w-3.5" /> {legacy ? "Modern UI" : "Win98 UI"}
      </a>
    </div>
  );
}
