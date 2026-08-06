import { Card } from "@/components/ui/card";
import { tone } from "@/lib/tones";

// Compact KPI card: icon in a tinted circle, value, label, optional hint and
// action slot. Only ever fed real backend fields — no invented numbers.
export default function MetricCard({
  icon: Icon,
  label,
  value,
  hint,
  tone: toneName = "neutral",
  action,
}) {
  const t = tone(toneName);
  return (
    <Card className="flex items-center gap-3 p-5">
      {Icon && (
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${t.dot}`}
        >
          <Icon className="h-4 w-4" aria-hidden />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="text-meta text-muted">{label}</div>
        <div className="tabular truncate text-[22px] font-semibold leading-7 text-ink">
          {value}
        </div>
        {hint && <div className="truncate text-[11px] leading-4 text-muted">{hint}</div>}
        {action && <div className="mt-1">{action}</div>}
      </div>
    </Card>
  );
}
