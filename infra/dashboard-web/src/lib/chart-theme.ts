// Colours and defaults for recharts, read from the CSS design tokens so charts
// follow the theme (including the hidden /legacy skin).

const token = (name: string, alpha = 1) => `hsl(var(--${name}) / ${alpha})`;

export const chart = {
  series: [1, 2, 3, 4, 5].map((i) => token(`chart-${i}`)),
  up: token("up"),
  down: token("down"),
  upFill: token("up", 0.12),
  downFill: token("down", 0.12),
  grid: token("border"),
  axis: token("muted-foreground"),
  primary: token("primary"),
  primaryFill: token("primary", 0.1),
  tick: { fontSize: 11, fill: token("muted-foreground") },
  tooltip: {
    contentStyle: {
      background: token("card"),
      border: `1px solid ${token("border")}`,
      borderRadius: 6,
      fontSize: 12,
      boxShadow: "none",
    },
    labelStyle: { color: token("muted-foreground") },
  },
} as const;
