// Colored badge for a scouting observation's severity (1-5).
export default function SeverityBadge({ value }) {
  if (value == null) return null;
  let cls = "bg-gray-100 text-gray-700";
  if (value >= 4) cls = "bg-red-100 text-red-800";
  else if (value === 3) cls = "bg-amber-100 text-amber-800";
  else cls = "bg-green-100 text-green-800";
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      severity {value}/5
    </span>
  );
}
