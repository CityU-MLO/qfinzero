"use client";

import { useEffect, useState } from "react";
import { LineChart, Settings2 } from "lucide-react";

import { AllocatePanel } from "@/components/broker/allocate-panel";
import { EnterPanel } from "@/components/broker/enter-panel";
import { Landing } from "@/components/broker/landing";
import { Terminal } from "@/components/broker/terminal";
import { useT } from "@/components/locale-provider";
import { PmbSettingsPanel } from "@/components/pmb/settings-panel";
import { PageHeader } from "@/components/ui/page-header";
import { Segmented } from "@/components/ui/segmented";

type View = "landing" | "allocate" | "enter" | "terminal";
type Tab = "trade" | "settings";

interface Live {
  sessionId: string;
  accountId: string;
  watchlist: string[];
  futures: string[];
}

const TABS = [
  { value: "trade", label: ["Trade", "交易"], icon: LineChart },
  { value: "settings", label: ["Broker settings", "交易设置"], icon: Settings2 },
] as const;

export default function BrokerPage() {
  const t = useT();
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
          futures={live.futures}
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
        title={t("Paper broker", "模拟券商")}
        description={t(
          "Trade against historical market data minute by minute, with a clock you control. Agents use the same broker through the pmb_* tools.",
          "基于历史行情逐分钟交易，时钟由你控制。智能体通过 pmb_* 工具使用同一个模拟券商。",
        )}
        actions={
          <Segmented
            value={tab}
            onChange={setTab}
            options={TABS.map((o) => ({ ...o, label: t(o.label[0], o.label[1]) }))}
          />
        }
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
