"use client";

import { useState } from "react";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Eye, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/lib/time";
import type { SanityResponse } from "@/lib/types";

type FilterStatus = "all" | "pass" | "warn" | "fail";

async function fetchSanity(): Promise<SanityResponse> {
  const response = await fetch("/api/npp/admin/sanity", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<SanityResponse>;
}

function statusVariant(status: "pass" | "warn" | "fail"): "success" | "warn" | "danger" {
  if (status === "pass") return "success";
  if (status === "warn") return "warn";
  return "danger";
}

function StatusFilterCard({
  label,
  value,
  status,
  isActive,
  onClick,
  colorClass,
}: {
  label: string;
  value: number;
  status: FilterStatus;
  isActive: boolean;
  onClick: () => void;
  colorClass: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`transition-all duration-200 ${
        isActive
          ? "ring-2 ring-offset-2 ring-primary"
          : "hover:ring-2 hover:ring-offset-1 hover:ring-muted-foreground/20"
      }`}
    >
      <Card className={isActive ? "bg-muted/50" : ""}>
        <CardContent className={`pt-6 ${colorClass}`}>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold">{value}</p>
        </CardContent>
      </Card>
    </button>
  );
}

function SamplesDrawer({
  checkName,
  status,
  samples,
  onClose,
}: {
  checkName: string;
  status: "pass" | "warn" | "fail";
  samples: Record<string, unknown>[];
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <Card className="flex max-h-[80vh] w-full max-w-3xl flex-col shadow-2xl">
        <CardHeader className="border-b pb-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Badge variant={statusVariant(status)}>{status.toUpperCase()}</Badge>
              <CardTitle className="text-base">{checkName}</CardTitle>
            </div>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            {samples.length} sample{samples.length !== 1 ? "s" : ""} showing
          </p>
        </CardHeader>
        <CardContent className="flex-1 overflow-auto p-4">
          {samples.length === 0 ? (
            <p className="text-center text-muted-foreground">No samples available</p>
          ) : (
            <pre className="overflow-auto rounded-md bg-muted p-4 text-xs">
              {JSON.stringify(samples, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function SanityReport() {
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [selectedSamples, setSelectedSamples] = useState<{
    name: string;
    status: "pass" | "warn" | "fail";
    samples: Record<string, unknown>[];
  } | null>(null);

  const sanity = useQuery({
    queryKey: ["sanity-report"],
    queryFn: fetchSanity,
  });

  const totalRows = sanity.data?.checks.reduce((sum, check) => sum + check.count, 0) ?? 0;

  const filteredChecks = sanity.data?.checks.filter((check) => {
    if (filter === "all") return true;
    return check.status === filter;
  }) ?? [];

  const handleFilterClick = (status: FilterStatus) => {
    setFilter((prev) => (prev === status ? "all" : status));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <p className="text-sm text-muted-foreground">
            Last checked:{" "}
            {sanity.data ? (
              <span className="font-medium text-foreground">
                {formatDateTime(sanity.data.checked_at)}
              </span>
            ) : sanity.isFetching ? (
              <span className="flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                Checking...
              </span>
            ) : (
              <span className="italic text-muted-foreground/60">Never</span>
            )}
          </p>
        </div>
        <Button
          onClick={() => void sanity.refetch()}
          disabled={sanity.isFetching}
          className="min-w-[100px]"
        >
          {sanity.isFetching ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Running...
            </>
          ) : (
            "Run Checks"
          )}
        </Button>
      </div>

      {sanity.data ? (
        <div className="grid gap-3 md:grid-cols-4">
          <StatusFilterCard
            label="Total Checks"
            value={sanity.data.summary.total}
            status="all"
            isActive={filter === "all"}
            onClick={() => handleFilterClick("all")}
            colorClass=""
          />
          <StatusFilterCard
            label="Pass"
            value={sanity.data.summary.pass}
            status="pass"
            isActive={filter === "pass"}
            onClick={() => handleFilterClick("pass")}
            colorClass="text-emerald-700"
          />
          <StatusFilterCard
            label="Warn"
            value={sanity.data.summary.warn}
            status="warn"
            isActive={filter === "warn"}
            onClick={() => handleFilterClick("warn")}
            colorClass="text-amber-700"
          />
          <StatusFilterCard
            label="Fail"
            value={sanity.data.summary.fail}
            status="fail"
            isActive={filter === "fail"}
            onClick={() => handleFilterClick("fail")}
            colorClass="text-rose-700"
          />
        </div>
      ) : null}

      {sanity.data && totalRows > 0 && (
        <p className="text-xs text-muted-foreground">
          Total rows evaluated: <span className="font-medium">{totalRows}</span>
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Sanity Check Details</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-48">Check</TableHead>
                <TableHead className="w-20">Status</TableHead>
                <TableHead className="w-16">Count</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Samples</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredChecks.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                    {filter !== "all"
                      ? `No ${filter} checks found`
                      : "No sanity checks available"}
                  </TableCell>
                </TableRow>
              ) : (
                filteredChecks.map((check) => (
                  <TableRow key={check.name}>
                    <TableCell className="font-medium">{check.name}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(check.status)}>{check.status}</Badge>
                    </TableCell>
                    <TableCell>{check.count}</TableCell>
                    <TableCell className="text-muted-foreground">{check.description}</TableCell>
                    <TableCell>
                      {check.samples.length === 0 ? (
                        <span className="text-muted-foreground/50">-</span>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 gap-1 text-xs"
                          onClick={() =>
                            setSelectedSamples({
                              name: check.name,
                              status: check.status,
                              samples: check.samples,
                            })
                          }
                        >
                          <Eye className="h-3 w-3" />
                          View {check.samples.length}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          {sanity.isError ? (
            <p className="mt-4 text-sm text-destructive">
              {(sanity.error as Error).message}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {selectedSamples && (
        <SamplesDrawer
          checkName={selectedSamples.name}
          status={selectedSamples.status}
          samples={selectedSamples.samples}
          onClose={() => setSelectedSamples(null)}
        />
      )}
    </div>
  );
}
