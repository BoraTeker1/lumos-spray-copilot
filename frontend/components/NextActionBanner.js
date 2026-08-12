import { TriangleAlert, CircleCheck } from "lucide-react";
import { tone, URGENCY_TONES } from "@/lib/tones";

// Compact prioritized next-action banner. Issue + operational consequence come
// verbatim/derived from the server-computed overview entry; `primary` and
// `secondary` are action slots (Button / link) supplied by the page.
// Tone follows real urgency — red for conflict/overdue harvest, amber for open
// work, neutral when all clear.
export default function NextActionBanner({
  issue,
  consequence,
  urgency,
  primary,
  secondary,
}) {
  if (!issue) return null;
  const toneName = URGENCY_TONES[urgency] || "neutral";
  const t = tone(toneName);
  const Icon = toneName === "neutral" ? CircleCheck : TriangleAlert;
  return (
    <div className={`flex flex-wrap items-center gap-3 rounded-card border px-4 py-3 ${t.box}`}>
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${t.dot}`}>
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      {/* basis-64 lets the text block claim a full row on a phone, pushing the
          actions onto their own line instead of squeezing them off-screen. */}
      <div className="min-w-0 flex-1 basis-64">
        <div className={`text-sm font-semibold ${t.text}`}>{issue}</div>
        {consequence && <div className="text-xs text-muted">{consequence}</div>}
      </div>
      {(primary || secondary) && (
        <div className="flex flex-wrap items-center gap-2">
          {secondary}
          {primary}
        </div>
      )}
    </div>
  );
}
