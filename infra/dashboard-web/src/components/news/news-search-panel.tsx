"use client";

import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useT } from "@/components/locale-provider";

type NewsFilters = {
  tickers: string;
  startUtc: string;
  endUtc: string;
  keyword: string;
  publisher: string;
  limit: number;
  /** keep articles with at least this much text ("" = every article) */
  minContent?: "" | "summary" | "full";
};

export function NewsSearchPanel({
  filters,
  onChange,
  onSearch,
  onPreset,
  isLoading,
}: {
  filters: NewsFilters;
  onChange: (next: NewsFilters) => void;
  onSearch: () => void;
  onPreset: (preset: "aapl_window" | "nvda_last_day" | "macro_earnings") => void;
  isLoading: boolean;
}) {
  const t = useT();
  const hasFilters = filters.tickers || filters.keyword || filters.publisher || filters.startUtc || filters.endUtc || filters.minContent;

  return (
    <div className="space-y-6 rounded-lg border bg-card p-5">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase text-muted-foreground/70">{t("Ticker(s)", "代码")}</Label>
          <Input 
            value={filters.tickers} 
            onChange={(e) => onChange({ ...filters, tickers: e.target.value })} 
            placeholder="AAPL,MSFT" 
            className="bg-card"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase text-muted-foreground/70">{t("Publisher", "发布方")}</Label>
          <Input 
            value={filters.publisher} 
            onChange={(e) => onChange({ ...filters, publisher: e.target.value })} 
            placeholder="Reuters" 
            className="bg-card"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase text-muted-foreground/70">{t("Keyword", "关键词")}</Label>
          <Input 
            value={filters.keyword} 
            onChange={(e) => onChange({ ...filters, keyword: e.target.value })} 
            placeholder="earnings" 
            className="bg-card"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase text-muted-foreground/70">{t("Content", "内容")}</Label>
          <select
            value={filters.minContent ?? ""}
            onChange={(e) => onChange({ ...filters, minContent: e.target.value as NewsFilters["minContent"] })}
            className="flex h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
          >
            <option value="">{t("Any (headlines too)", "全部（含仅标题）")}</option>
            <option value="summary">{t("With a summary or full text", "有摘要或全文")}</option>
            <option value="full">{t("Full text only", "只要全文")}</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase text-muted-foreground/70">{t("Start (UTC)", "开始 (UTC)")}</Label>
          <Input 
            type="datetime-local" 
            value={filters.startUtc} 
            onChange={(e) => onChange({ ...filters, startUtc: e.target.value })} 
            className="bg-card"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase text-muted-foreground/70">{t("End (UTC)", "结束 (UTC)")}</Label>
          <Input 
            type="datetime-local" 
            value={filters.endUtc} 
            onChange={(e) => onChange({ ...filters, endUtc: e.target.value })} 
            className="bg-card"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 border-t pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-semibold text-muted-foreground/50 mr-1">{t("Presets", "预设")}</span>
          <PresetBadge onClick={() => onPreset("aapl_window")}>AAPL 2025-01-01~01-03</PresetBadge>
          <PresetBadge onClick={() => onPreset("nvda_last_day")}>{t("NVDA Last 24h", "NVDA 最近 24 小时")}</PresetBadge>
          <PresetBadge onClick={() => onPreset("macro_earnings")}>{t("Keyword: earnings", "关键词：earnings")}</PresetBadge>
          
          {hasFilters && (
            <Button 
              variant="ghost" 
              size="sm" 
              className="h-7 px-2 text-[10px] text-destructive hover:bg-destructive/5"
              onClick={() => onChange({
                tickers: "",
                startUtc: "",
                endUtc: "",
                keyword: "",
                publisher: "",
                limit: 50,
                minContent: "",
              })}
            >
              <X className="mr-1 h-3 w-3" /> {t("Clear Filters", "清除筛选")}
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Label className="text-xs font-medium text-muted-foreground">{t("Limit", "条数上限")}</Label>
            <Input
              type="number"
              min={1}
              max={500}
              value={filters.limit}
              onChange={(e) => onChange({ ...filters, limit: Number(e.target.value) || 50 })}
              className="h-8 w-16 bg-card text-xs"
            />
          </div>
          <Button 
            onClick={onSearch} 
            disabled={isLoading} 
            className="h-9 gap-2 shadow-primary/20"
          >
            {isLoading ? (
              <span className="flex items-center gap-1.5"><div className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" /> {t("Searching...", "搜索中...")}</span>
            ) : (
              <span className="flex items-center gap-1.5"><Search className="h-4 w-4" /> {t("Run Query", "查询")}</span>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

function PresetBadge({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <Badge 
      variant="secondary" 
      className="cursor-pointer border-transparent bg-primary/5 text-primary transition-all hover:bg-primary/10 hover:"
      onClick={onClick}
    >
      {children}
    </Badge>
  );
}
