import { forwardRef } from "react";
import { cn } from "@/lib/utils";

// shadcn-style button, converted to plain JS. Solid dark green is reserved for
// the primary action ("default"); "secondary" is the outlined-green table/row
// action; everything else stays neutral.
const VARIANTS = {
  default: "bg-leaf-700 text-white shadow-sm hover:bg-leaf-800",
  secondary:
    "border border-leaf-600/40 bg-surface text-leaf-700 shadow-sm hover:bg-leaf-50",
  outline: "border border-line bg-surface text-ink shadow-sm hover:bg-canvas",
  ghost: "text-muted hover:bg-canvas hover:text-ink",
  destructive:
    "border border-risk-line bg-surface text-risk-fg shadow-sm hover:bg-risk-bg",
};

// `lg` exists for mobile primaries: the spec's minimum touch target is 44px.
const SIZES = {
  default: "h-10 px-4 py-2",
  sm: "h-9 rounded-control px-3 text-xs",
  lg: "h-11 px-5",
  icon: "h-9 w-9",
};

export const Button = forwardRef(function Button(
  { className, variant = "default", size = "default", ...props },
  ref
) {
  return (
    <button
      ref={ref}
      className={cn(
        // Focus is a BLUE 2px ring with a 2px offset (design spec) — never the
        // brand green, which would read as an approval state.
        "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-control text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
        VARIANTS[variant],
        SIZES[size],
        className
      )}
      {...props}
    />
  );
});
