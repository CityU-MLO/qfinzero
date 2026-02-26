"use client";

import { ExternalLink } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { NppEvent } from "@/lib/types";

function EmptyValue() {
  return <span className="text-muted-foreground/30">—</span>;
}

export function NewsTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: NppEvent[];
  selectedId: string | null;
  onSelect: (event: NppEvent) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border bg-white/70 shadow-sm">
      <Table>
        <TableHeader className="bg-muted/30">
          <TableRow>
            <TableHead className="w-40 text-xs font-bold uppercase tracking-wider">Time (UTC)</TableHead>
            <TableHead className="text-xs font-bold uppercase tracking-wider">Title</TableHead>
            <TableHead className="w-32 text-xs font-bold uppercase tracking-wider">Publisher</TableHead>
            <TableHead className="w-32 text-xs font-bold uppercase tracking-wider">Tickers</TableHead>
            <TableHead className="w-20 text-xs font-bold uppercase tracking-wider">Rating</TableHead>
            <TableHead className="w-16 text-right text-xs font-bold uppercase tracking-wider">URL</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="h-32 text-center text-sm text-muted-foreground">
                No news entries found matching your query.
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => {
              const isActive = selectedId === row.event_id;
              const payload = row.payload ?? {};
              const publisher = typeof payload.publisher === "string" ? payload.publisher : null;
              const rating = typeof (payload as Record<string, unknown>).rating === "string" ? String((payload as Record<string, unknown>).rating) : null;
              const url = typeof payload.article_url === "string" ? payload.article_url : null;

              return (
                <TableRow
                  key={row.event_id}
                  className={cn(
                    "group cursor-pointer transition-colors hover:bg-muted/50",
                    isActive && "bg-primary/5 hover:bg-primary/10"
                  )}
                  onClick={() => onSelect(row)}
                >
                  <TableCell className="text-[11px] font-medium text-muted-foreground whitespace-nowrap">
                    {formatDateTime(row.time_utc)}
                  </TableCell>
                  <TableCell className="max-w-md">
                    <div 
                      className={cn(
                        "line-clamp-1 text-sm font-medium tracking-tight group-hover:text-primary transition-colors",
                        isActive && "text-primary font-semibold"
                      )} 
                      title={row.title}
                    >
                      {row.title}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    {publisher || <EmptyValue />}
                  </TableCell>
                  <TableCell>
                    {row.tickers.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {row.tickers.slice(0, 3).map(t => (
                          <span key={t} className="rounded bg-muted px-1 text-[10px] font-bold text-muted-foreground">
                            {t}
                          </span>
                        ))}
                        {row.tickers.length > 3 && <span className="text-[10px] text-muted-foreground">+{row.tickers.length - 3}</span>}
                      </div>
                    ) : (
                      <EmptyValue />
                    )}
                  </TableCell>
                  <TableCell className="text-xs font-medium">
                    {rating || <EmptyValue />}
                  </TableCell>
                  <TableCell className="text-right">
                    {url ? (
                      <a 
                        href={url} 
                        target="_blank" 
                        rel="noreferrer" 
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md text-primary transition-colors hover:bg-primary/10"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    ) : (
                      <EmptyValue />
                    )}
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );
}
