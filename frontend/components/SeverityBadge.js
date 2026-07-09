import { Badge } from "@/components/ui/badge";

// Badge for a scouting observation's severity (1-5). Neutral for low severity;
// amber/red only when it becomes actionable.
export default function SeverityBadge({ value }) {
  if (value == null) return null;
  const variant = value >= 4 ? "red" : value === 3 ? "amber" : "neutral";
  return <Badge variant={variant}>severity {value}/5</Badge>;
}
