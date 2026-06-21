// Small shared display helpers so formatting stays consistent across the app.

// Currency follows the farm's country: US → USD ($), Türkiye → TRY (₺).
export function currencySymbol(country) {
  return (country || "").toUpperCase() === "TR" ? "₺" : "$";
}

export function formatCost(value, country) {
  if (value == null) return "—";
  const symbol = currencySymbol(country);
  const locale = symbol === "₺" ? "tr-TR" : "en-US";
  return `${symbol}${Number(value).toLocaleString(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`;
}

// US specialty-crop growers think in acres; Türkiye greenhouses in m².
export function formatArea(value, country) {
  if (value == null) return "—";
  const unit = (country || "").toUpperCase() === "TR" ? "m²" : "acres";
  return `${value} ${unit}`;
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
