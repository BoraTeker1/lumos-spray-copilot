import { CircleAlert, Info, ShieldCheck, TriangleAlert } from "lucide-react";
import { tone } from "@/lib/tones";

// One inline banner recipe for the statements that sit above a page's content:
// an error, a caveat about what the numbers mean, a scope disclaimer.
//
// Before this, six files each hand-rolled their own
// `rounded-* border border-X-line bg-X-bg p-? text-sm text-X-fg` div, so the
// same kind of statement had three different paddings and two different radii
// depending on which page you were on. Colors resolve through the shared tone
// registry, so a banner can never drift from the badge that means the same thing.
const DEFAULT_ICONS = {
  risk: CircleAlert,
  warn: TriangleAlert,
  inspect: TriangleAlert,
  info: Info,
  good: ShieldCheck,
  review: Info,
  neutral: Info,
};

export default function Callout({
  tone: toneName = "info",
  icon: IconOverride,
  title,
  children,
  className = "",
}) {
  const t = tone(toneName);
  const Icon = IconOverride || DEFAULT_ICONS[toneName] || Info;
  return (
    <div
      className={`flex items-start gap-2.5 rounded-card border px-4 py-3 text-sm ${t.box} ${t.text} ${className}`}
    >
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${t.icon}`} aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={title ? "mt-0.5" : ""}>{children}</div>}
      </div>
    </div>
  );
}
