"use client";

// Settings → Rates: load Treasury / FRED rate files into the rates store that
// option Greeks discount with. Loaded rates are kept apart and laid over the
// massive base on every conversion, so updates never drop them.

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Landmark, Loader2 } from "lucide-react";

import { useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { dataAdmin, type RatesFile, type RatesRange } from "@/lib/data-admin";

const TENOR_LABEL: Record<string, string> = {
  yield_1_month: "1M", yield_3_month: "3M", yield_1_year: "1Y", yield_2_year: "2Y", yield_5_year: "5Y",
  yield_10_year: "10Y", yield_30_year: "30Y",
};

function Range({ r, label }: { r: RatesRange; label: string }) {
  const t = useT();
  return (
    <div className="rounded-lg border px-4 py-3">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {r ? (
        <>
          <div className="mt-1 font-mono text-sm">{r.start} → <b>{r.end}</b> <span className="text-muted-foreground">· {r.dates.toLocaleString()} {t("days", "天")}</span></div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(r.tenors).map(([k, n]) => (
              <span key={k} className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${n ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground line-through"}`}
                    title={t(`${n} days`, `${n} 天`)}>{TENOR_LABEL[k] ?? k}</span>
            ))}
          </div>
        </>
      ) : <div className="mt-1 text-sm text-muted-foreground">{t("none", "无")}</div>}
    </div>
  );
}

export function RatesPanel() {
  const t = useT();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["rates", "status"], queryFn: dataAdmin.ratesStatus });
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [files, setFiles] = React.useState<{ name: string; content: string }[]>([]);
  const [preview, setPreview] = React.useState<RatesFile[] | null>(null);
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = React.useState(false);

  const pick = async (list: FileList | null) => {
    if (!list?.length) return;
    setMsg(null);
    setPreview(null);
    const read = await Promise.all([...list].slice(0, 20).map(async (f) => ({ name: f.name, content: await f.text() })));
    setFiles(read);
    setBusy(true);
    try {
      setPreview((await dataAdmin.ratesPreview(read)).files);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    setBusy(true);
    try {
      const r = await dataAdmin.ratesApply(files);
      setMsg({ ok: true, text: t(`Loaded ${r.new_dates} new day(s); the store now ends ${r.status.store?.end}. Greeks use it right away.`,
        `已载入 ${r.new_dates} 个新日期；利率存储现在截至 ${r.status.store?.end}。Greeks 会立即使用。`) });
      setFiles([]);
      setPreview(null);
      await qc.invalidateQueries({ queryKey: ["rates", "status"] });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card id="rates" className="scroll-mt-20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Landmark className="h-4 w-4" />{t("Interest rates", "利率")}</CardTitle>
        <CardDescription>
          {t("Option Greeks discount with the Treasury curve of the day; without a rate for a date they use the latest earlier one. Load the U.S. Treasury daily par yield curve CSV or FRED series (DGS1MO, DGS3MO, DGS1, DGS2, DGS5, DGS10, DGS30), in percent.",
            "期权 Greeks 用当天的国债收益率曲线折现；某天没有利率时用此前最近的一天。可加载美国财政部每日收益率曲线 CSV 或 FRED 序列（DGS1MO、DGS3MO、DGS1、DGS2、DGS5、DGS10、DGS30），单位为百分比。")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {status.isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        {status.data && (
          <div className="grid gap-3 md:grid-cols-2">
            <Range r={status.data.store} label={t("Rates store (used by Greeks)", "利率存储（Greeks 使用）")} />
            <Range r={status.data.loaded} label={t("Loaded files (kept across updates)", "已加载的文件（更新后保留）")} />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv,text/csv" multiple className="hidden" onChange={(e) => { void pick(e.target.files); e.target.value = ""; }} />
          <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()} disabled={busy}><FileUp /> {t("Choose CSV files", "选择 CSV 文件")}</Button>
          {busy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>
        {preview && (
          <div className="space-y-2">
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-[13px]">
                <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                  <tr><th className="px-3 py-2">{t("File", "文件")}</th><th className="px-3 py-2">{t("Days", "天数")}</th><th className="px-3 py-2">{t("Range", "范围")}</th><th className="px-3 py-2">{t("Tenors", "期限")}</th><th className="px-3 py-2">{t("Latest", "最新")}</th></tr>
                </thead>
                <tbody>
                  {preview.map((p) => {
                    const last = p.sample[p.sample.length - 1];
                    return (
                      <tr key={p.file} className="border-t">
                        <td className="px-3 py-2 font-mono text-xs">{p.file}</td>
                        <td className="px-3 py-2">{p.dates.toLocaleString()}</td>
                        <td className="px-3 py-2 font-mono text-xs">{p.start} → {p.end}</td>
                        <td className="px-3 py-2">{p.tenors.map((x) => TENOR_LABEL[x] ?? x).join(" ")}
                          {p.ignored_columns.length > 0 && <span className="ml-1 text-xs text-muted-foreground">({t("ignored", "忽略")}: {p.ignored_columns.join(", ")})</span>}</td>
                        <td className="px-3 py-2 font-mono text-xs">{last ? `${last[0]}: ${Object.entries(last[1]).map(([k, v]) => `${TENOR_LABEL[k]} ${v}%`).join(" ")}` : ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Button size="sm" onClick={apply} disabled={busy}>{t("Load into the rates store", "载入利率存储")}</Button>
          </div>
        )}
        {msg && <Alert variant={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      </CardContent>
    </Card>
  );
}
