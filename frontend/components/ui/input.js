import { forwardRef } from "react";
import { cn } from "@/lib/utils";

// Shared form-control recipe — used by Input, Select, and Textarea so every
// form field in the app focuses and rounds the same way.
//
// The focus ring is BLUE, not brand green (design spec): on a screen where
// green means "approved", a green ring on an empty field is a false signal.
export const fieldClass =
  "h-10 w-full rounded-control border border-line bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-muted/70 focus:border-focus focus:outline-none focus:ring-2 focus:ring-focus/30 disabled:cursor-not-allowed disabled:bg-canvas disabled:text-muted";

// Invalid state: red border plus a visible message. Color alone never conveys
// the error — call sites pair this with helper text.
export const fieldErrorClass =
  "border-risk-fg focus:border-risk-fg focus:ring-risk-fg/25";

export const Input = forwardRef(function Input(
  { className, invalid = false, ...props },
  ref
) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(fieldClass, invalid && fieldErrorClass, className)}
      {...props}
    />
  );
});

// Helper/error text under a control. `tone="error"` is the red variant.
export function FieldHint({ className, tone = "muted", ...props }) {
  return (
    <p
      className={cn(
        "mt-1 text-meta",
        tone === "error" ? "text-risk-fg" : "text-muted",
        className
      )}
      {...props}
    />
  );
}
