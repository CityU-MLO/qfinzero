"use client";

import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type NewsFilters = {
  tickers: string;
  startUtc: string;
  endUtc: string;
  keyword: string;
  publisher: string;
  limit: number;
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
  const hasFilters = filters.tickers || filters.keyword || filters.publisher || filters.startUtc || filters.endUtc;

  return (
    <div className="space-y-6 rounded-2xl border bg-white/80 p-5 shadow-sm backdrop-blur">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <div className="space-y-1.5">
          <Label className="text-xs font-bold uppercase text-muted-foreground/70">Ticker(s)</Label>
          <Input 
            value={filters.tickers} 
            onChange={(e) => onChange({ ...filters, tickers: e.target.value })} 
            placeholder="AAPL,MSFT" 
            className="bg-white/50"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-bold uppercase text-muted-foreground/70">Publisher</Label>
          <Input 
            value={filters.publisher} 
            onChange={(e) => onChange({ ...filters, publisher: e.target.value })} 
            placeholder="Reuters" 
            className="bg-white/50"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-bold uppercase text-muted-foreground/70">Keyword</Label>
          <Input 
            value={filters.keyword} 
            onChange={(e) => onChange({ ...filters, keyword: e.target.value })} 
            placeholder="earnings" 
            className="bg-white/50"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-bold uppercase text-muted-foreground/70">Start (UTC)</Label>
          <Input 
            type="datetime-local" 
            value={filters.startUtc} 
            onChange={(e) => onChange({ ...filters, startUtc: e.target.value })} 
            className="bg-white/50"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-bold uppercase text-muted-foreground/70">End (UTC)</Label>
          <Input 
            type="datetime-local" 
            value={filters.endUtc} 
            onChange={(e) => onChange({ ...filters, endUtc: e.target.value })} 
            className="bg-white/50"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 border-t pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 mr-1">Presets</span>
          <PresetBadge onClick={() => onPreset("aapl_window")}>AAPL 2025-01-01~01-03</PresetBadge>
          <PresetBadge onClick={() => onPreset("nvda_last_day")}>NVDA Last 24h</PresetBadge>
          <PresetBadge onClick={() => onPreset("macro_earnings")}>Keyword: earnings</PresetBadge>
          
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
              })}
            >
              <X className="mr-1 h-3 w-3" /> Clear Filters
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Label className="text-xs font-medium text-muted-foreground">Limit</Label>
            <Input
              type="number"
              min={1}
              max={500}
              value={filters.limit}
              onChange={(e) => onChange({ ...filters, limit: Number(e.target.value) || 50 })}
              className="h-8 w-16 bg-white/50 text-xs"
            />
          </div>
          <Button 
            onClick={onSearch} 
            disabled={isLoading} 
            className="h-9 gap-2 shadow-md shadow-primary/20"
          >
            {isLoading ? (
              <span className="flex items-center gap-1.5"><div className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" /> Searching...</span>
            ) : (
              <span className="flex items-center gap-1.5"><Search className="h-4 w-4" /> Run Query</span>
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
      className="cursor-pointer border-transparent bg-primary/5 text-primary transition-all hover:bg-primary/10 hover:shadow-sm"
      onClick={onClick}
    >
      {children}
    </Badge>
  );
}
