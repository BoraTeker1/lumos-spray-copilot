import { CircleCheck, Compass, Search, ThermometerSun, Users } from "lucide-react";

// Prominent, farmer-friendly "next action" banner derived from the rule engine.
// This is the highest-priority action on the Overview tab.
const STYLES = {
  "Harvest timing risk — review before picking": {
    cls: "border-red-200 bg-red-50 text-red-900",
    Icon: ThermometerSun,
  },
  "Review with agronomist before spraying": {
    cls: "border-amber-200 bg-amber-50 text-amber-900",
    Icon: Users,
  },
  "Inspect first": {
    cls: "border-sky-200 bg-sky-50 text-sky-900",
    Icon: Search,
  },
  "Low risk — continue monitoring": {
    cls: "border-green-200 bg-green-50 text-green-900",
    Icon: CircleCheck,
  },
};

export default function NextActionCard({ action }) {
  if (!action) return null;
  const meta = STYLES[action] || { cls: "border-gray-200 bg-gray-50 text-gray-900", Icon: Compass };
  const Icon = meta.Icon;
  return (
    <div className={`rounded-lg border p-3.5 ${meta.cls}`}>
      <div className="text-[11px] font-medium uppercase tracking-wide opacity-70">
        Highest-priority action
      </div>
      <div className="mt-1 flex items-center gap-2 text-base font-semibold">
        <Icon className="h-4 w-4 shrink-0" aria-hidden />
        {action}
      </div>
    </div>
  );
}
