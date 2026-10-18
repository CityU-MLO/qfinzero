import { NewsBrowser } from "@/components/news/news-browser";
import { PageHeader } from "@/components/ui/page-header";
import { getT } from "@/lib/i18n-server";

export async function generateMetadata() {
  const t = await getT();
  return { title: t("News", "新闻") };
}

export default async function NewsPage() {
  const t = await getT();
  return (
    <>
      <PageHeader
        title={t("News", "新闻")}
        description={t(
          "Search articles by ticker, time, publisher or keyword; inspect rows and export the result set.",
          "按代码、时间、发布方或关键词搜索文章；查看行详情并导出结果。",
        )}
      />
      <NewsBrowser />
    </>
  );
}
