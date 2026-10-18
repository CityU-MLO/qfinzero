"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/time";
import type { EspEvent } from "@/lib/types";
import { useT } from "@/components/locale-provider";

function importanceBadgeVariant(importance: string): "success" | "warn" | "danger" | "secondary" | "outline" {
  if (importance === "high") return "danger";
  if (importance === "medium") return "warn";
  if (importance === "low") return "success";
  return "outline";
}

function statusBadgeVariant(status: string): "success" | "secondary" | "outline" {
  if (status === "occurred") return "success";
  if (status === "updated") return "secondary";
  return "outline";
}

const IMPORTANCE_ZH: Record<string, string> = { high: "高", medium: "中", low: "低" };
const STATUS_ZH: Record<string, string> = { occurred: "已发生", updated: "已更新", scheduled: "已排期", confirmed: "已确认", estimated: "预估" };

function TruncateCell({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <TableCell className={className} title={children}>
      <span className="block max-w-full truncate">{children || "-"}</span>
    </TableCell>
  );
}

export function CalendarTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: EspEvent[];
  selectedId: string | null;
  onSelect: (row: EspEvent) => void;
}) {
  const t = useT();
  return (
    <div className="rounded-lg border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-44">{t("time_utc", "时间 (UTC)")}</TableHead>
            <TableHead>{t("title", "标题")}</TableHead>
            <TableHead className="w-20">{t("importance", "重要性")}</TableHead>
            <TableHead className="w-24">{t("status", "状态")}</TableHead>
            <TableHead className="w-32">{t("tickers", "代码")}</TableHead>
            <TableHead className="w-28">{t("country", "国家/地区")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow
              key={row.event_id}
              className="cursor-pointer"
              data-state={selectedId === row.event_id ? "selected" : undefined}
              onClick={() => onSelect(row)}
            >
              <TableCell className="whitespace-nowrap">{formatDateTime(row.time_utc)}</TableCell>
              <TableCell className="max-w-xl" title={row.title}>
                <span className="block max-w-full truncate">{row.title}</span>
              </TableCell>
              <TableCell>
                <Badge variant={importanceBadgeVariant(row.importance)}>{t(row.importance, IMPORTANCE_ZH[row.importance] ?? row.importance)}</Badge>
              </TableCell>
              <TableCell>
                <Badge variant={statusBadgeVariant(row.status)}>{t(row.status, STATUS_ZH[row.status] ?? row.status)}</Badge>
              </TableCell>
              <TruncateCell className="max-w-32">{row.tickers.join(", ")}</TruncateCell>
              <TableCell>{row.country}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
