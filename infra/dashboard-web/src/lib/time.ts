export function safeDate(input: string | number | Date | null | undefined): Date | null {
  if (input == null || input === 0 || input === "0") {
    return null;
  }

  if (input instanceof Date) {
    return Number.isNaN(input.getTime()) ? null : input;
  }

  if (typeof input === "number") {
    if (input <= 0) return null;
    let millis = input;
    if (input > 1_000_000_000_000_000) {
      millis = Math.floor(input / 1_000_000);
    }
    const date = new Date(millis);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime()) || parsed.getTime() <= 0) {
    return null;
  }
  return parsed;
}

export function formatRelative(input: string | number | Date | null | undefined): string {
  const date = safeDate(input);
  if (!date) {
    return "-";
  }

  const diffMs = Date.now() - date.getTime();
  const abs = Math.abs(diffMs);

  if (abs < 60_000) {
    return `${Math.round(abs / 1000)}s`;
  }
  if (abs < 3_600_000) {
    return `${Math.round(abs / 60_000)}m`;
  }
  if (abs < 86_400_000) {
    return `${Math.round(abs / 3_600_000)}h`;
  }
  return `${Math.round(abs / 86_400_000)}d`;
}

export function formatDateTime(input: string | number | Date | null | undefined): string {
  const date = safeDate(input);
  if (!date) {
    return "-";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(date);
}

export function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null) {
    return "-";
  }

  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return `${h}h ${m}m`;
}
