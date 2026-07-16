import { Badge } from "@/components/ui/badge";
import { tone } from "@/lib/tones";
import { statusMeta } from "@/lib/status";

// One-line semantic status pill: icon + explicit text + tone — never color alone.
// `kind` selects the canonical vocabulary (verdict/workflow/outcome/evidence/review).
export default function StatusBadge({ kind, value, className = "" }) {
  const meta = statusMeta(kind, value);
  const Icon = meta.icon;
  return (
    <Badge variant={tone(meta.tone).badge} className={`whitespace-nowrap ${className}`}>
      <Icon aria-hidden />
      {meta.label}
    </Badge>
  );
}
