import { CircleCheck, Compass, Search, ThermometerSun, Users } from "lucide-react";
import { tone } from "@/lib/tones";

// Prominent, farmer-friendly "next action" banner derived from the rule engine.
// This is the highest-priority action on the Overview tab. Keys are the exact
// backend action strings; tones come from the shared table.
const STYLES = {
  "Harvest timing risk — review before picking": { tone: "risk", Icon: ThermometerSun },
  "Review with agronomist before spraying": { tone: "warn", Icon: Users },
  "Inspect first": { tone: "info", Icon: Search },
  "Low risk — continue monitoring": { tone: "good", Icon: CircleCheck },
};

export default function NextActionCard({ action }) {
  if (!action) return null;
  const meta = STYLES[action] || { tone: "neutral", Icon: Compass };
  const t = tone(meta.tone);
  const cls = `${t.box} ${t.text}`;
  const Icon = meta.Icon;
  return (
    <div className={`rounded-card border p-3.5 ${cls}`}>
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
