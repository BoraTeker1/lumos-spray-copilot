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
    // items-start + h-full: cards in a KPI row align on their top edge and match
    // heights, so a two-line hint on one card cannot shift its neighbours' values
    // off the shared baseline.
    <Card className="flex h-full items-start gap-3 p-4">
      {Icon && (
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${t.dot}`}
        >
          <Icon className="h-4 w-4" aria-hidden />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="text-meta text-muted">{label}</div>
        <div className="tabular text-[22px] font-semibold leading-7 text-ink">{value}</div>
        {/* Wrapped to two lines, never truncated: a KPI that cuts off its own
            qualifier ("blocking conflicts before spr…") loses the caveat that
            makes the number honest. */}
        {hint && (
          <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-muted">{hint}</div>
        )}
        {action && <div className="mt-1.5">{action}</div>}
      </div>
    </Card>
  );
}
