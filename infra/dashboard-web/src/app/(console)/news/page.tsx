import { NewsBrowser } from "@/components/news/news-browser";
import { PageHeader } from "@/components/ui/page-header";

export const metadata = { title: "News" };

export default function NewsPage() {
  return (
    <>
      <PageHeader title="News" description="Search articles by ticker, time, publisher or keyword; inspect rows and export the result set." />
      <NewsBrowser />
    </>
  );
}
