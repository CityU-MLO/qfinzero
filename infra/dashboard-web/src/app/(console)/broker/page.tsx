"use client";

import { useEffect, useState } from "react";
import { LineChart, Settings2 } from "lucide-react";

import { AllocatePanel } from "@/components/broker/allocate-panel";
import { EnterPanel } from "@/components/broker/enter-panel";
import { Landing } from "@/components/broker/landing";
import { Terminal } from "@/components/broker/terminal";
import { PmbSettingsPanel } from "@/components/pmb/settings-panel";
import { PageHeader } from "@/components/ui/page-header";
import { Segmented } from "@/components/ui/segmented";

type View = "landing" | "allocate" | "enter" | "terminal";
type Tab = "trade" | "settings";

interface Live {
  sessionId: string;
  accountId: string;
  watchlist: string[];
}

const TABS = [
  { value: "trade", label: "Trade", icon: LineChart },
  { value: "settings", label: "Broker settings", icon: Settings2 },
] as const;

export default function BrokerPage() {
  const [tab, setTab] = useState<Tab>("trade");
  const [view, setView] = useState<View>("landing");
  const [presetAccount, setPresetAccount] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);

  useEffect(() => {
    if (window.location.hash === "#settings") setTab("settings");
  }, []);

  if (view === "terminal" && live) {
    // the session terminal fills the console below the top bar
    return (
      <div className="-mx-4 -mb-12 -mt-6 h-[calc(100vh-3rem)] border-b md:-mx-6">
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
    );
  }

  return (
    <div>
      <PageHeader
        title="Paper broker"
        description="Trade against historical market data minute by minute, with a clock you control. Agents use the same broker through the pmb_* tools."
        actions={<Segmented value={tab} onChange={setTab} options={TABS} />}
      />
      {tab === "settings" ? (
        <div className="max-w-3xl">
          <PmbSettingsPanel />
        </div>
      ) : (
        <>
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
        </>
      )}
    </div>
  );
}
