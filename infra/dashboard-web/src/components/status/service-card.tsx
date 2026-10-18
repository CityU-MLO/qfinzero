import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, Copy, ExternalLink, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { formatDateTime, formatRelative, formatUptime } from "@/lib/time";
import type { ServiceStatusCard } from "@/lib/types";
import { useT } from "@/components/locale-provider";

function StateBadge({ state }: { state: ServiceStatusCard["state"] }) {
  const t = useT();
  if (state === "running") {
    return (
      <Badge variant="success" className="gap-1 px-2 py-0.5">
        <CheckCircle2 className="h-3.5 w-3.5" /> {t("Running", "运行中")}
      </Badge>
    );
  }
  if (state === "stale") {
    return (
      <Badge variant="warn" className="gap-1 px-2 py-0.5">
        <AlertTriangle className="h-3.5 w-3.5" /> {t("Stale", "过期")}
      </Badge>
    );
  }
  return (
    <Badge variant="destructive" className="gap-1 px-2 py-0.5">
      <XCircle className="h-3.5 w-3.5" /> {t("Down", "离线")}
    </Badge>
  );
}

function MetricRow({ label, value, className }: { label: string; value: string | number | null; className?: string }) {
  return (
    <div className={cn("flex items-center justify-between border-b py-1.5 text-sm last:border-b-0", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value ?? "-"}</span>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-6 w-6 text-muted-foreground hover:text-primary"
      onClick={handleCopy}
      title={copied ? t("Copied", "已复制") : t("Copy URL", "复制 URL")}
      aria-label={t("Copy URL", "复制 URL")}
    >
      <Copy className={cn("h-3 w-3 transition-transform", copied && "scale-110 text-success")} />
    </Button>
  );
}

export function ServiceCard({ card }: { card: ServiceStatusCard }) {
  const t = useT();
  const freshness = card.freshness?.sources ? Object.entries(card.freshness.sources) : [];
  const isDown = card.state === "down";
  const displayUrl = card.baseUrl.replace(/^https?:\/\//, "").split("/")[0];

  return (
    <Card className={cn("transition-all", isDown && "border-destructive/30 bg-destructive/5")}>
      <CardHeader className="space-y-3 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="truncate text-lg">{card.name}</CardTitle>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <span title={card.baseUrl}>{displayUrl}</span>
              <CopyButton text={card.baseUrl} />
              <a
                href={card.baseUrl}
                target="_blank"
                rel="noreferrer"
                title={t("Open service", "打开服务")}
                className="inline-flex h-6 w-6 items-center justify-center rounded-md hover:bg-accent hover:text-accent-foreground"
              >
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </div>
          <StateBadge state={card.state} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <div className={cn("space-y-0.5", isDown && "opacity-50")}>
          <MetricRow label={t("Version", "版本")} value={card.version ?? (isDown ? t("N/A", "不可用") : "-")} />
          <MetricRow label={t("Uptime", "运行时长")} value={isDown ? "0s" : formatUptime(card.uptimeSeconds)} />
          <MetricRow label={t("Req/5m", "请求/5分钟")} value={card.requests5m} />
          <MetricRow label={t("Err/5m", "错误/5分钟")} value={card.errors5m} />
          <MetricRow label={t("Active", "活跃请求")} value={card.activeRequests} />
          {(card.freshness !== null || isDown) && (
            <MetricRow label={t("Latest Data", "最新数据")} value={card.latestDataAt ? `${formatDateTime(card.latestDataAt)} (${t(`${formatRelative(card.latestDataAt)} ago`, `${formatRelative(card.latestDataAt)}前`)})` : (isDown ? t("N/A", "不可用") : "-")} />
          )}
        </div>

        {card.staleReason ? <p className="rounded-md bg-warning/10 px-2 py-1 text-xs text-warning">{card.staleReason}</p> : null}

        {isDown ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-8 text-center">
            <XCircle className="mb-2 h-8 w-8 text-destructive/40" />
            <p className="text-xs font-medium text-destructive/70">{t("Service Unavailable", "服务不可用")}</p>
            <p className="mt-0.5 text-[10px] text-muted-foreground">{t("Cannot fetch freshness metrics", "无法获取新鲜度指标")}</p>
          </div>
        ) : freshness.length > 0 ? (
          <div className="rounded-lg border bg-card overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/30">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="h-9 px-3 text-[11px] font-semibold">{t("Source", "数据源")}</TableHead>
                  <TableHead className="h-9 px-3 text-[11px] font-semibold">{t("Latest", "最新")}</TableHead>
                  <TableHead className="h-9 px-3 text-right text-[11px] font-semibold">{t("Rows", "行数")}</TableHead>
                  <TableHead className="h-9 px-3 text-right text-[11px] font-semibold">{t("Keys", "键数")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {freshness.map(([name, src]) => {
                  const latest = src.latest_timestamp ?? src.latest_date;
                  const keysText = src.unique_keys != null ? `${src.unique_keys} ${src.unique_key_label ?? ""}` : "-";
                  return (
                    <TableRow key={name} className="hover:bg-muted/20">
                      <TableCell className="px-3 py-2 text-xs font-medium">{name}</TableCell>
                      <TableCell className="px-3 py-2 text-xs whitespace-nowrap">{formatDateTime(latest ?? null)}</TableCell>
                      <TableCell className="px-3 py-2 text-right text-xs tabular-nums">{src.record_count ?? "-"}</TableCell>
                      <TableCell 
                        className="max-w-[100px] truncate px-3 py-2 text-right text-xs tabular-nums" 
                        title={keysText}
                      >
                        {keysText}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
