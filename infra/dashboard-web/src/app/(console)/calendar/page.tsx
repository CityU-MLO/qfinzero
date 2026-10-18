import { CalendarBrowser } from "@/components/calendar/calendar-browser";

export default function CalendarPage() {
  return (
    <main className="space-y-4">
      <section>
        <h2 className="text-xl font-semibold">SQLite Calendar Browser</h2>
        <p className="text-sm text-muted-foreground">
          Browse earnings/economic tables with filters, JSON row details, exports, and coverage heatmap.
        </p>
      </section>
      <CalendarBrowser />
    </main>
  );
}
