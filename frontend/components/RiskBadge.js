import { Badge } from "@/components/ui/badge";
import { RISK_LEVEL_TONES, tone } from "@/lib/tones";

// Colored badge for a recommendation's risk level. Renders nothing when there
// is no assessment yet (no ambiguous "not yet assessed" state).
const STYLES = {
  low: { variant: tone(RISK_LEVEL_TONES.low).badge, label: "Low risk" },
  moderate: { variant: tone(RISK_LEVEL_TONES.moderate).badge, label: "Moderate risk" },
  elevated: { variant: tone(RISK_LEVEL_TONES.elevated).badge, label: "Elevated risk" },
};

export default function RiskBadge({ level }) {
  const meta = STYLES[level];
  if (!meta) return null;
  return (
    <Badge variant={meta.variant}>
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
      {meta.label}
    </Badge>
  );
}
