import { Droplets, Eye } from "lucide-react";
import { formatCost, formatDate } from "@/lib/format";
import SeverityBadge from "@/components/SeverityBadge";

// Unified recent-activity timeline: spray events and scouting observations,
// newest first. Pass `limit` to cap the number of rows (Overview view).
export default function ActivityTimeline({ sprays = [], observations = [], country, limit }) {
  const items = [
    ...sprays.map((s) => ({
      type: "spray",
      date: s.application_date,
      id: `s-${s.id}`,
      title: s.product_name,
      meta: [
        s.active_ingredient,
        s.pre_harvest_interval_days != null ? `PHI ${s.pre_harvest_interval_days}d` : null,
        s.re_entry_interval_hours != null ? `REI ${s.re_entry_interval_hours}h` : null,
      ]
        .filter(Boolean)
        .join(" · "),
      right: s.cost != null ? formatCost(s.cost, country) : null,
    })),
    ...observations.map((o) => ({
      type: "scout",
      date: o.observation_date,
      id: `o-${o.id}`,
      title: o.visible_issue || "Scouting observation",
      meta: o.crop_stage || "",
      severity: o.severity_1_to_5,
    })),
  ].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

  const shown = limit ? items.slice(0, limit) : items;

  if (shown.length === 0) {
    return <p className="text-sm text-gray-500">No sprays or scouting notes recorded yet.</p>;
  }

  return (
    <ol className="relative space-y-0 border-l border-gray-200 pl-5">
      {shown.map((item) => (
        <li key={item.id} className="relative pb-4 last:pb-0">
          <span
            className={`absolute -left-[27px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full ring-4 ring-white ${
              item.type === "spray" ? "bg-sky-100 text-sky-700" : "bg-gray-100 text-gray-600"
            }`}
          >
            {item.type === "spray" ? (
              <Droplets className="h-3 w-3" />
            ) : (
              <Eye className="h-3 w-3" />
            )}
          </span>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate text-sm font-medium text-gray-900">{item.title}</span>
                {item.severity != null && <SeverityBadge value={item.severity} />}
              </div>
              <div className="text-xs text-gray-500">
                {formatDate(item.date)}
                {item.meta && ` · ${item.meta}`}
                {" · "}
                {item.type === "spray" ? "spray" : "scouting"}
              </div>
            </div>
            {item.right && (
              <span className="shrink-0 text-sm font-medium text-gray-700">{item.right}</span>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
