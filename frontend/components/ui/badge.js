import { cn } from "@/lib/utils";

// Status badge — soft-tinted pill. Green = verified positive states only;
// amber/orange/red = actionable review states; purple = a licensed human still
// has to sign; blue = informational; neutral/outline for everything else.
//
// The KEYS keep their historical color names so the ~45 existing call sites
// (many of them dynamic lookups) need no edits; the values behind them resolve
// through the semantic token pairs in tailwind.config.js.
const VARIANTS = {
  neutral: "bg-draft-bg text-draft-fg ring-draft-line",
  green: "bg-ok-bg text-ok-fg ring-ok-line",
  amber: "bg-warn-bg text-warn-fg ring-warn-line",
  inspect: "bg-inspect-bg text-inspect-fg ring-inspect-line",
  red: "bg-risk-bg text-risk-fg ring-risk-line",
  blue: "bg-info-bg text-info-fg ring-info-line",
  purple: "bg-review-bg text-review-fg ring-review-line",
  outline: "bg-surface text-muted ring-line",
};

export function Badge({ className, variant = "neutral", ...props }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold leading-4 ring-1 ring-inset [&_svg]:size-3 [&_svg]:shrink-0",
        VARIANTS[variant] || VARIANTS.neutral,
        className
      )}
      {...props}
    />
  );
}
