"use client";

import { X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Right-hand record panel for the master/detail list screens (scouting,
// applications, the farm field list).
//
// PURELY PRESENTATIONAL. It renders a row object the page has already fetched
// and derived — it performs no lookup, no filtering and no status derivation of
// its own, so it can never disagree with the table it sits beside.

export function DetailRow({ label, value, tone }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1 text-sm">
      <span className="shrink-0 text-muted">{label}</span>
      <span
        className={cn(
          "min-w-0 text-right font-medium",
          tone === "warn" ? "text-warn-fg" : tone === "risk" ? "text-risk-fg" : "text-ink"
        )}
      >
        {value ?? "—"}
      </span>
    </div>
  );
}

export function DetailSection({ title, children, className }) {
  return (
    <div className={cn("border-t border-line px-4 py-3 first:border-t-0", className)}>
      {title && (
        <h4 className="mb-1.5 text-sm font-semibold text-ink">{title}</h4>
      )}
      {children}
    </div>
  );
}

// A vertical chain of stages (planned decision → application → follow-up).
// `stages` is [{ label, value, icon, tone }] built by the caller from existing
// row fields — this renders it, it does not infer the chain.
export function DetailChain({ stages = [] }) {
  return (
    <ol className="space-y-0">
      {stages.map((s, i) => {
        const Icon = s.icon;
        const last = i === stages.length - 1;
        return (
          <li key={s.label} className="flex gap-2.5">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                  s.tone === "good"
                    ? "bg-ok-bg text-ok-fg"
                    : s.tone === "warn"
                      ? "bg-warn-bg text-warn-fg"
                      : "bg-draft-bg text-muted"
                )}
              >
                {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden /> : null}
              </span>
              {!last && <span className="my-0.5 w-px flex-1 bg-line" />}
            </div>
            <div className={cn("flex min-w-0 flex-1 justify-between gap-3", last ? "pb-0" : "pb-3")}>
              <span className="text-sm text-ink">{s.label}</span>
              <span className="shrink-0 text-sm font-medium text-muted">{s.value}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default function DetailPanel({
  title,
  subtitle,
  badges,
  onClose,
  footer,
  children,
  className,
}) {
  return (
    <Card className={cn("flex flex-col overflow-hidden", className)}>
      <div className="relative border-b border-line px-4 py-3 pr-10">
        <h3 className="text-section font-semibold text-ink">{title}</h3>
        {subtitle && <p className="mt-0.5 text-meta text-muted">{subtitle}</p>}
        {badges && <div className="mt-2 flex flex-wrap items-center gap-1.5">{badges}</div>}
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close details"
            className="absolute right-3 top-3 rounded-control p-1 text-muted transition-colors hover:bg-canvas hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1">{children}</div>
      {footer && (
        <div className="flex flex-col gap-2 border-t border-line px-4 py-3">{footer}</div>
      )}
    </Card>
  );
}
