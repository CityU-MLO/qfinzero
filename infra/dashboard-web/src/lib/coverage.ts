export type DailyCount = { date: string; count: number };

export function buildCoverageHeatmap(data: DailyCount[], startDate: string | null, endDate: string | null): DailyCount[] {
  if (!startDate || !endDate) {
    return data;
  }

  const byDate = new Map(data.map((item) => [item.date, item.count]));
  const result: DailyCount[] = [];

  let cursor = new Date(`${startDate}T00:00:00Z`);
  const end = new Date(`${endDate}T00:00:00Z`);

  while (cursor.getTime() <= end.getTime()) {
    const key = cursor.toISOString().slice(0, 10);
    result.push({
      date: key,
      count: byDate.get(key) ?? 0,
    });
    cursor = new Date(cursor.getTime() + 86_400_000);
  }

  return result;
}
