import { DataSetup } from "@/components/data/data-setup";
import { PageHeader } from "@/components/ui/page-header";
import { getT } from "@/lib/i18n-server";

export async function generateMetadata() {
  const t = await getT();
  return { title: t("Data setup", "数据导入") };
}

export default async function DataSetupPage() {
  const t = await getT();
  return (
    <>
      <PageHeader
        title={t("Data setup utility", "数据导入工具")}
        description={t(
          "Bring Databento and massive data into QFinZero: pick files already on the server, or download with your key. Everything is converted to QFinZero storage.",
          "把 Databento 和 massive 数据导入 QFinZero：选择服务器上已有的文件，或用你的密钥下载，全部自动转换为 QFinZero 存储格式。",
        )}
      />
      <DataSetup />
    </>
  );
}
