import { SanityReport } from "@/components/sanity/sanity-report";
import { PageHeader } from "@/components/ui/page-header";

export const metadata = { title: "Data checks" };

export default function SanityPage() {
  return (
    <>
      <PageHeader title="Data checks" description="Quality checks on the event stores, with samples of every warning and failure." />
      <SanityReport />
    </>
  );
}
