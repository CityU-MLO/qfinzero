"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { JsonViewer } from "@/components/news/json-viewer";
import { formatDateTime } from "@/lib/time";
import type { NewsBodyResponse, NppEvent } from "@/lib/types";

export function NewsDetailDrawer({
  selected,
  article,
  onClose,
}: {
  selected: NppEvent | null;
  article: NewsBodyResponse | null;
  onClose: () => void;
}) {
  if (!selected) {
    return (
      <Card className="flex h-[400px] flex-col items-center justify-center border-dashed bg-muted/30 text-center">
        <p className="text-sm font-medium text-muted-foreground">No entry selected</p>
        <p className="mt-1 text-xs text-muted-foreground/60">Select a row from the table to view details.</p>
      </Card>
    );
  }

  const payload = selected.payload ?? {};

  return (
    <Card className="sticky top-4 flex h-[calc(100vh-120px)] flex-col shadow-xl ring-1 ring-black/5">
      <CardHeader className="border-b bg-muted/30 pb-4 pr-12">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <CardTitle className="line-clamp-2 text-sm font-bold leading-tight">{selected.title}</CardTitle>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-medium text-muted-foreground uppercase">{formatDateTime(selected.time_utc)}</span>
              <span className="h-1 w-1 rounded-full bg-muted-foreground/30" />
              <span className="text-[10px] font-bold text-primary uppercase">{selected.source}</span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-4 top-4 h-8 w-8 rounded-full hover:bg-muted"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-auto p-4 scrollbar-thin">
        <div className="space-y-6">
          {article?.article_url ? (
            <Button asChild variant="outline" size="sm" className="w-full justify-start gap-2 shadow-sm">
              <a href={article.article_url} target="_blank" rel="noreferrer">
                <span>View Original Source</span>
              </a>
            </Button>
          ) : null}

          <div className="space-y-4">
            <JsonViewer data={payload} title="Event Payload" />
            <JsonViewer data={article} title="Article Metadata" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
