import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

// Labelled form field, and the inline error that goes under a form.
//
// `Field` was written inside PreSpraySheet, where its comment recorded the
// defect it fixed: every control there used its placeholder as its only label,
// so the field name vanished the moment someone typed. That fix was never
// carried to the other three data-entry forms, which kept ~18 placeholder-only
// controls between them — including `Pre-harvest interval (days)` and
// `Re-entry interval (hours)`, the two most consequential numbers a grower
// types. It lives here now so there is one labelled-field recipe, not two.
//
// A wrapping <label> is used rather than htmlFor/id pairs: it associates the
// control with no ids to keep unique, which is what the 72 existing wrapping
// labels in this codebase already do.
export function Field({ label, hint, required = false, className, children }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-xs font-medium text-ink">
        {label}
        {/* A bare `*` is not an accessible required marker — the word is in the
            label text so a screen reader announces it. */}
        {required && <span className="ml-1 font-normal text-muted">(required)</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  );
}

// Inline submit/load error. `role="alert"` is the point: these messages were
// red text and nothing else, so a screen-reader user submitted a form, got no
// announcement, and had no way to know the save had failed. Colour must never
// be the only carrier of a failure, hence the icon as well.
//
// Presentation only — it renders the message the call site already had, and
// invents no copy of its own.
export function FormError({ children, className, size = "default" }) {
  if (!children) return null;
  return (
    <p
      role="alert"
      className={cn(
        "flex items-start gap-1.5 text-risk-fg",
        size === "sm" ? "text-xs" : "text-sm",
        className
      )}
    >
      <AlertCircle
        className={cn("mt-px shrink-0", size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5")}
        aria-hidden
      />
      <span className="min-w-0">{children}</span>
    </p>
  );
}
