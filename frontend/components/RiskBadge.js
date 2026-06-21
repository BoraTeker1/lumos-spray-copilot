// Small colored badge for a recommendation's risk level.
const STYLES = {
  low: { cls: "bg-green-100 text-green-800 ring-green-600/20", label: "Low risk", dot: "🟢" },
  moderate: { cls: "bg-amber-100 text-amber-800 ring-amber-600/20", label: "Moderate risk", dot: "🟡" },
  elevated: { cls: "bg-red-100 text-red-800 ring-red-600/20", label: "Elevated risk", dot: "🔴" },
};

export default function RiskBadge({ level }) {
  const meta = STYLES[level] || {
    cls: "bg-gray-100 text-gray-600 ring-gray-500/20",
    label: "Not yet assessed",
    dot: "⚪",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${meta.cls}`}
    >
      <span aria-hidden>{meta.dot}</span>
      {meta.label}
    </span>
  );
}
