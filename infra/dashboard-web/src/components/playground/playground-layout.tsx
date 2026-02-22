"use client";

import { useState } from "react";
import { ConfigPanel, PlaygroundConfig, loadConfig } from "./config-panel";
import { ChatPanel } from "./chat-panel";

export function PlaygroundLayout() {
  const [config, setConfig] = useState<PlaygroundConfig>(loadConfig);

  return (
    <div className="flex flex-1 min-h-0 rounded-2xl border bg-white/80 shadow-sm overflow-hidden">
      <ConfigPanel config={config} onChange={setConfig} />
      <ChatPanel config={config} />
    </div>
  );
}
