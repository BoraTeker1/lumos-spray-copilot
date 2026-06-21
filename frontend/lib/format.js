// Small shared display helpers so formatting stays consistent across the app.

// Both demo farms are in Türkiye, so we show costs in Turkish lira.
export function formatCost(value) {
  if (value == null) return "—";
  return `₺${Number(value).toLocaleString("tr-TR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`;
}

// Render an ISO date (YYYY-MM-DD) in a friendlier form.
export function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
