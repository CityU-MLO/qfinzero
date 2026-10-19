import { Suspense } from "react";

import { QFZView } from "@/components/qfzview/qfzview";

export const metadata = { title: "QFZView" };

export default function ViewPage() {
  return (
    <Suspense fallback={null}>
      <QFZView />
    </Suspense>
  );
}
