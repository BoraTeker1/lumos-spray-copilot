import { TriangleAlert, CircleCheck } from "lucide-react";
import { tone, URGENCY_TONES } from "@/lib/tones";

// Mockup-style NEXT ACTION banner. Text comes verbatim from the server-computed
// overview entry (`next_action` + `why`); tone follows the real urgency —
// red for a timing conflict, amber for open work, neutral when all clear.
export default function NextActionBanner({ nextAction, why, urgency, cta }) {
  if (!nextAction) return null;
  const toneName = URGENCY_TONES[urgency] || "neutral";
  const t = tone(toneName);
  const Icon = toneName === "neutral" ? CircleCheck : TriangleAlert;
  return (
    <div className={`flex flex-wrap items-center gap-3 rounded-xl border p-4 ${t.box}`}>
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${t.dot}`}>
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className={`text-[11px] font-semibold uppercase tracking-wide opacity-70 ${t.text}`}>
          Next action
        </div>
        <div className={`text-sm font-semibold sm:text-base ${t.text}`}>{nextAction}</div>
        {why && <div className="text-xs text-gray-600">{why}</div>}
      </div>
      {cta && <div className="shrink-0">{cta}</div>}
    </div>
  );
}
