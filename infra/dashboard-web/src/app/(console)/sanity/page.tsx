import { SanityReport } from "@/components/sanity/sanity-report";

export default function SanityPage() {
  return (
    <main className="space-y-4">
      <section>
        <h2 className="text-xl font-semibold">Data Sanity Checks</h2>
        <p className="text-sm text-muted-foreground">
          Run quality checks and inspect pass/warn/fail samples for fast debugging.
        </p>
      </section>
      <SanityReport />
    </main>
  );
}
