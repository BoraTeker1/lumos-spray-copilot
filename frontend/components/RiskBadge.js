import { Badge } from "@/components/ui/badge";

// Colored badge for a recommendation's risk level. Renders nothing when there
// is no assessment yet (no ambiguous "not yet assessed" state).
const STYLES = {
  low: { variant: "green", label: "Low risk" },
  moderate: { variant: "amber", label: "Moderate risk" },
  elevated: { variant: "red", label: "Elevated risk" },
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
