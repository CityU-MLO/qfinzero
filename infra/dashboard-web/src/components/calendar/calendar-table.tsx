"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/time";
import type { EspEvent } from "@/lib/types";

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
  return (
    <div className="rounded-lg border bg-white/70">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-44">time_utc</TableHead>
            <TableHead>title</TableHead>
            <TableHead className="w-20">importance</TableHead>
            <TableHead className="w-24">status</TableHead>
            <TableHead className="w-32">tickers</TableHead>
            <TableHead className="w-28">country</TableHead>
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
                <Badge variant={importanceBadgeVariant(row.importance)}>{row.importance}</Badge>
              </TableCell>
              <TableCell>
                <Badge variant={statusBadgeVariant(row.status)}>{row.status}</Badge>
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
