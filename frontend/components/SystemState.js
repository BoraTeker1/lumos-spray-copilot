"use client";

import { CircleX, RefreshCw, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Loading / error / stale shells, siblings of EmptyState.
//
// These are PRESENTATION ONLY. Every call site passes its own message string
// and, where one already exists, its own retry handler — nothing here invents
// copy or behaviour. In particular:
//   * `message` is required; there is no generic default, so a page cannot
//     silently lose the specific sentence it used to show.
//   * the retry button renders ONLY when `onRetry` is supplied. A page that has
//     no retry affordance today does not gain one by adopting this component.
//   * nothing here fetches, clears filters, or touches farm context.

export function LoadingState({ message, rows = 3, className }) {
  return (
    <div className={cn("space-y-3", className)} role="status" aria-live="polite">
      <div className="space-y-2" aria-hidden>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="h-9 w-9 shrink-0 animate-pulse rounded-control bg-draft-bg" />
            <div className="flex-1 space-y-1.5">
              <div className="h-3 w-1/3 animate-pulse rounded bg-draft-bg" />
              <div className="h-3 w-2/3 animate-pulse rounded bg-draft-bg" />
            </div>
          </div>
        ))}
      </div>
      <p className="flex items-center gap-1.5 text-sm text-muted">
        <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden />
        {message}
      </p>
    </div>
  );
}

export function ErrorState({ title, message, onRetry, retryLabel = "Try again", className }) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-2 rounded-card border border-risk-line bg-risk-bg/40 px-6 py-8 text-center",
        className
      )}
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-risk-bg text-risk-fg">
        <CircleX className="h-5 w-5" aria-hidden />
      </span>
      {title && <div className="text-sm font-semibold text-ink">{title}</div>}
      <p className="max-w-md break-words text-sm text-risk-fg">{message}</p>
      {/* Reassurance, not a claim about the server: a failed GET changed nothing. */}
      <p className="text-meta text-muted">Your data was not changed.</p>
      {onRetry && (
        <Button type="button" size="sm" variant="outline" onClick={onRetry} className="mt-1">
          <RefreshCw />
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

export function StaleState({ message, onRefresh, refreshLabel = "Refresh", className }) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-card border border-warn-line bg-warn-bg px-4 py-2.5 text-sm text-warn-fg",
        className
      )}
    >
      <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{message}</span>
      {onRefresh && (
        <Button type="button" size="sm" variant="outline" onClick={onRefresh}>
          {refreshLabel}
        </Button>
      )}
    </div>
  );
}
