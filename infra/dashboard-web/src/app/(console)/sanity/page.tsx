import { SanityReport } from "@/components/sanity/sanity-report";
import { PageHeader } from "@/components/ui/page-header";
import { getT } from "@/lib/i18n-server";

export async function generateMetadata() {
  const t = await getT();
  return { title: t("Data checks", "数据检查") };
}

export default async function SanityPage() {
  const t = await getT();
  return (
    <>
      <PageHeader
        title={t("Data checks", "数据检查")}
        description={t(
          "Quality checks on the event stores, with samples of every warning and failure.",
          "事件存储的质量检查，附带每项警告和失败的样例。",
        )}
      />
      <SanityReport />
    </>
  );
}
