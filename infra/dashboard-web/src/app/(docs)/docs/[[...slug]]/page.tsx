import { DocsHub } from "@/components/docs/docs-hub";
import { getT } from "@/lib/i18n-server";

export async function generateMetadata() {
  const t = await getT();
  return { title: t("Documentation", "文档") };
}

export default async function DocsPage({ params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return <DocsHub slug={(slug ?? []).map(decodeURIComponent)} />;
}
