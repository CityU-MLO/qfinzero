import { CalendarBrowser } from "@/components/calendar/calendar-browser";
import { PageHeader } from "@/components/ui/page-header";

export const metadata = { title: "Calendar" };

export default function CalendarPage() {
  return (
    <>
      <PageHeader title="Calendar" description="Earnings and economic releases with filters, row details, exports and a coverage map." />
      <CalendarBrowser />
    </>
  );
}
