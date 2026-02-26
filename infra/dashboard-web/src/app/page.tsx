import { StatusDashboard } from "@/components/status/status-dashboard";

export default function StatusPage() {
  return (
    <main className="space-y-4">
      <section>
        <h2 className="text-xl font-semibold">Health & Status</h2>
        <p className="text-sm text-muted-foreground">
          Unified status cards for UPQ / NPP / PMB with freshness and request/error trend signals.
        </p>
      </section>
      <StatusDashboard />
    </main>
  );
}
