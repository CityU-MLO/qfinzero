"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useT } from "@/components/locale-provider";

type CalendarFilters = {
  startDate: string;
  endDate: string;
  tickers: string;
  country: string;
  minImportance: string;
  limit: number;
};

export function CalendarFiltersPanel({
  mode,
  filters,
  onMode,
  onChange,
  onQuery,
  loading,
  exportQuery,
}: {
  mode: "earnings" | "econ";
  filters: CalendarFilters;
  onMode: (mode: "earnings" | "econ") => void;
  onChange: (filters: CalendarFilters) => void;
  onQuery: () => void;
  loading: boolean;
  exportQuery?: string;
}) {
  const t = useT();
  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap gap-2">
        <Button variant={mode === "earnings" ? "default" : "outline"} onClick={() => onMode("earnings")}>{t("Earnings", "财报")}</Button>
        <Button variant={mode === "econ" ? "default" : "outline"} onClick={() => onMode("econ")}>{t("Economic", "经济数据")}</Button>
      </div>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-1.5">
          <Label>{t("Start Date", "开始日期")}</Label>
          <Input type="date" value={filters.startDate} onChange={(e) => onChange({ ...filters, startDate: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label>{t("End Date", "结束日期")}</Label>
          <Input type="date" value={filters.endDate} onChange={(e) => onChange({ ...filters, endDate: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label>{t("Limit", "条数上限")}</Label>
          <Input type="number" value={filters.limit} onChange={(e) => onChange({ ...filters, limit: Number(e.target.value) || 100 })} />
        </div>

        {mode === "earnings" ? (
          <div className="space-y-1.5">
            <Label>{t("Tickers", "代码")}</Label>
            <Input value={filters.tickers} placeholder="AAPL,NVDA" onChange={(e) => onChange({ ...filters, tickers: e.target.value })} />
          </div>
        ) : (
          <div className="space-y-1.5">
            <Label>{t("Country", "国家/地区")}</Label>
            <Input value={filters.country} placeholder="United States" onChange={(e) => onChange({ ...filters, country: e.target.value })} />
          </div>
        )}

        <div className="space-y-1.5">
          <Label>{t("Importance", "重要性")}</Label>
          <Select value={filters.minImportance} onChange={(e) => onChange({ ...filters, minImportance: e.target.value })}>
            <option value="">{t("Any", "全部")}</option>
            {mode === "earnings" ? (
              <>
                <option value="2">2+</option>
                <option value="4">4+</option>
              </>
            ) : (
              <>
                <option value="low">{t("low", "低")}</option>
                <option value="medium">{t("medium", "中")}</option>
                <option value="high">{t("high", "高")}</option>
              </>
            )}
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={onQuery} disabled={loading}>{loading ? t("Querying...", "查询中...") : t("Run Query", "查询")}</Button>
        {exportQuery && (
          <Button asChild variant="outline">
            <a href={exportQuery} target="_blank" rel="noreferrer">{t("Export CSV", "导出 CSV")}</a>
          </Button>
        )}
      </div>
    </div>
  );
}
