"use client";

import { useState, useEffect } from "react";
import { ConfigPanel, PlaygroundConfig, loadConfig, DEFAULT_CONFIG } from "./config-panel";
import { PlaygroundAssistant } from "./playground-assistant";

export function PlaygroundLayout() {
  const [config, setConfig] = useState<PlaygroundConfig>(DEFAULT_CONFIG);

  // Defer localStorage read to after hydration to avoid SSR/CSR mismatch
  useEffect(() => {
    setConfig(loadConfig());
  }, []);

  return (
    <div className="flex flex-1 min-h-0 gap-4">
      <PlaygroundAssistant config={config} />
      <ConfigPanel config={config} onChange={setConfig} />
    </div>
  );
}
