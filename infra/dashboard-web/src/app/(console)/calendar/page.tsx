import { CalendarBrowser } from "@/components/calendar/calendar-browser";
import { PageHeader } from "@/components/ui/page-header";
import { getT } from "@/lib/i18n-server";

export async function generateMetadata() {
  const t = await getT();
  return { title: t("Calendar", "日历") };
}

export default async function CalendarPage() {
  const t = await getT();
  return (
    <>
      <PageHeader
        title={t("Calendar", "日历")}
        description={t(
          "Earnings and economic releases with filters, row details, exports and a coverage map.",
          "财报与经济数据发布，支持筛选、行详情、导出和覆盖情况图。",
        )}
      />
      <CalendarBrowser />
    </>
  );
}
