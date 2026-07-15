import { Card } from "@/components/ui/card";
import { tone } from "@/lib/tones";

// Mockup-style KPI tile: icon in a tinted circle, big value, small label,
// optional hint line. Only ever fed real backend fields — no invented numbers.
export default function KpiTile({ icon: Icon, label, value, hint, tone: toneName = "neutral" }) {
  const t = tone(toneName);
  return (
    <Card className="flex items-center gap-3 p-4">
      {Icon && (
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${t.dot}`}
        >
          <Icon className="h-4 w-4" />
        </span>
      )}
      <div className="min-w-0">
        <div className="text-xs text-gray-500">{label}</div>
        <div className="truncate text-xl font-semibold text-gray-900">{value}</div>
        {hint && <div className="truncate text-[11px] text-gray-500">{hint}</div>}
      </div>
    </Card>
  );
}
