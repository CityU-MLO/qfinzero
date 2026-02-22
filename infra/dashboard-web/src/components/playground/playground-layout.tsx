"use client";

import { useState, useEffect } from "react";
import { ConfigPanel, PlaygroundConfig, loadConfig, DEFAULT_CONFIG } from "./config-panel";
import { ChatPanel } from "./chat-panel";

export function PlaygroundLayout() {
  const [config, setConfig] = useState<PlaygroundConfig>(DEFAULT_CONFIG);

  // Defer localStorage read to after hydration to avoid SSR/CSR mismatch
  useEffect(() => {
    setConfig(loadConfig());
  }, []);

  return (
    <div className="flex flex-1 min-h-0 rounded-2xl border bg-white/80 shadow-sm overflow-hidden">
      <ConfigPanel config={config} onChange={setConfig} />
      <ChatPanel config={config} />
    </div>
  );
}
