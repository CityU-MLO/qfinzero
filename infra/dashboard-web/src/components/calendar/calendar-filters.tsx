"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

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
  return (
    <div className="space-y-3 rounded-xl border bg-white/80 p-4">
      <div className="flex flex-wrap gap-2">
        <Button variant={mode === "earnings" ? "default" : "outline"} onClick={() => onMode("earnings")}>Earnings</Button>
        <Button variant={mode === "econ" ? "default" : "outline"} onClick={() => onMode("econ")}>Economic</Button>
      </div>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-1.5">
          <Label>Start Date</Label>
          <Input type="date" value={filters.startDate} onChange={(e) => onChange({ ...filters, startDate: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label>End Date</Label>
          <Input type="date" value={filters.endDate} onChange={(e) => onChange({ ...filters, endDate: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label>Limit</Label>
          <Input type="number" value={filters.limit} onChange={(e) => onChange({ ...filters, limit: Number(e.target.value) || 100 })} />
        </div>

        {mode === "earnings" ? (
          <div className="space-y-1.5">
            <Label>Tickers</Label>
            <Input value={filters.tickers} placeholder="AAPL,NVDA" onChange={(e) => onChange({ ...filters, tickers: e.target.value })} />
          </div>
        ) : (
          <div className="space-y-1.5">
            <Label>Country</Label>
            <Input value={filters.country} placeholder="United States" onChange={(e) => onChange({ ...filters, country: e.target.value })} />
          </div>
        )}

        <div className="space-y-1.5">
          <Label>Importance</Label>
          <Select value={filters.minImportance} onChange={(e) => onChange({ ...filters, minImportance: e.target.value })}>
            <option value="">Any</option>
            {mode === "earnings" ? (
              <>
                <option value="2">2+</option>
                <option value="4">4+</option>
              </>
            ) : (
              <>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </>
            )}
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={onQuery} disabled={loading}>{loading ? "Querying..." : "Run Query"}</Button>
        {exportQuery && (
          <Button asChild variant="outline">
            <a href={exportQuery} target="_blank" rel="noreferrer">Export CSV</a>
          </Button>
        )}
      </div>
    </div>
  );
}
