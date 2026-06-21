// Prominent, farmer-friendly "next action" banner derived from the rule engine.
const STYLES = {
  "Harvest timing risk — review before picking": {
    cls: "border-red-300 bg-red-50 text-red-900",
    icon: "🌡️",
  },
  "Review with agronomist before spraying": {
    cls: "border-amber-300 bg-amber-50 text-amber-900",
    icon: "👩‍🌾",
  },
  "Inspect first": {
    cls: "border-sky-300 bg-sky-50 text-sky-900",
    icon: "🔍",
  },
  "Low risk — continue monitoring": {
    cls: "border-green-300 bg-green-50 text-green-900",
    icon: "✅",
  },
};

export default function NextActionCard({ action }) {
  if (!action) return null;
  const meta = STYLES[action] || {
    cls: "border-gray-300 bg-gray-50 text-gray-900",
    icon: "🧭",
  };
  return (
    <div className={`rounded-lg border-2 p-4 ${meta.cls}`}>
      <div className="text-xs font-medium uppercase tracking-wide opacity-70">
        Suggested next action
      </div>
      <div className="mt-1 flex items-center gap-2 text-lg font-semibold">
        <span aria-hidden>{meta.icon}</span>
        {action}
      </div>
    </div>
  );
}
