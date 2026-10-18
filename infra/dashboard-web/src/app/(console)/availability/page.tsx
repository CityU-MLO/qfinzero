import { CoverageMap } from "@/components/coverage/coverage-map";
import { PageHeader } from "@/components/ui/page-header";
import { getT } from "@/lib/i18n-server";

export async function generateMetadata() {
  const t = await getT();
  return { title: t("Data availability", "数据可用性") };
}

export default async function AvailabilityPage() {
  const t = await getT();
  return (
    <>
      <PageHeader
        title={t("Data availability", "数据可用性")}
        description={t(
          "Which data exists for each ticker and day, with news, earnings and macro releases on the same time axis. Click a cell for details.",
          "按代码和日期查看有哪些数据，新闻、财报和宏观数据显示在同一时间轴上。点击单元格查看详情。",
        )}
      />
      <CoverageMap />
    </>
  );
}
